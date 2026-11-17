#!/usr/bin/env python3
"""Generate fast web display derivatives for archived artworks.

The archived master file is never modified. Each artwork additionally gets a
WebP copy with a maximum long edge of 1600 px, which keeps the public grid from
decoding multi-megapixel originals on every visit. Animated or undecodable
sources keep the archived master as their display asset.

Usage:
    python scripts/make-display-assets.py            # generate what is missing
    python scripts/make-display-assets.py --force    # regenerate everything
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from PIL import Image, ImageOps, UnidentifiedImageError
except ImportError:  # pragma: no cover - dependency hint
    sys.stderr.write(
        "Pillow is required for display derivatives.\n"
        "Install it with: python -m pip install 'Pillow>=10'\n"
    )
    raise SystemExit(2)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "artworks.json"
DOCS_ROOT = ROOT / "docs"
MAX_EDGE = 1600
WEBP_QUALITY = 85
MAX_DISPLAY_BYTES = 4 * 1024 * 1024
DERIVED_VARIANT = "derived_1600_webp"
FALLBACK_VARIANT = "original_fallback"
DISPLAY_POLICY = (
    "The archived master is kept byte-for-byte. A WebP display derivative with a "
    "maximum long edge of 1600 px (quality 85) is generated from it for the public "
    "grid; animated or undecodable sources keep the archived master as display asset."
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_current(work: dict, target: Path, force: bool) -> bool:
    if force:
        return False
    if work.get("display_variant") != DERIVED_VARIANT:
        return False
    if work.get("display_source_sha256") != work.get("sha256"):
        return False
    if not target.is_file():
        return False
    if target.stat().st_size != work.get("display_file_size"):
        return False
    return True


def fallback_to_master(work: dict) -> None:
    work.update(
        display_url=work["local_url"],
        display_variant=FALLBACK_VARIANT,
        display_mime_type=work["mime_type"],
        display_width=work["image_width"],
        display_height=work["image_height"],
        display_file_size=work["file_size"],
        display_sha256=work["sha256"],
        display_source_sha256=work["sha256"],
        display_generated_at=now_iso(),
    )


def build_derivative(work: dict, target: Path) -> tuple[int, int]:
    source = DOCS_ROOT / work["local_url"]
    if not source.is_file():
        raise FileNotFoundError("missing archived master " + str(source))

    with Image.open(source) as image:
        if getattr(image, "n_frames", 1) > 1:
            raise ValueError("animated source")
        image = ImageOps.exif_transpose(image)
        image.load()
        width, height = image.size
        scale = min(1.0, MAX_EDGE / max(width, height))
        if scale < 1.0:
            image = image.resize(
                (max(1, round(width * scale)), max(1, round(height * scale))),
                Image.Resampling.LANCZOS,
            )
        has_alpha = image.mode in ("RGBA", "LA") or (
            image.mode == "P" and "transparency" in image.info
        )
        prepared = image.convert("RGBA" if has_alpha else "RGB")
        display_width, display_height = prepared.size
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + ".tmp")
        prepared.save(temp, "WEBP", quality=WEBP_QUALITY, method=6)
        os.replace(temp, target)

    return display_width, display_height


def main() -> int:
    force = "--force" in sys.argv[1:]
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest.get("status") != "ready" or not isinstance(manifest.get("artists"), list):
        sys.stderr.write("data/artworks.json is not a ready archive; run the sync script first.\n")
        return 1

    stats = {"derived": 0, "skipped": 0, "fallback": 0, "display_bytes": 0}
    referenced = set()

    for record in manifest["artists"]:
        artist_id = str(record["artist_id"])
        for work in record["artworks"]:
            post_id = str(work["post_id"])
            rel = "assets/artists/" + artist_id + "/" + post_id + ".display.webp"
            target = DOCS_ROOT / rel

            if is_current(work, target, force):
                stats["skipped"] += 1
                stats["display_bytes"] += target.stat().st_size
                referenced.add(rel)
                continue

            try:
                display_width, display_height = build_derivative(work, target)
            except (ValueError, UnidentifiedImageError, OSError) as error:
                print("display fallback for post #" + post_id + ": " + str(error))
                fallback_to_master(work)
                stats["fallback"] += 1
                continue

            size = target.stat().st_size
            if size > MAX_DISPLAY_BYTES:
                target.unlink(missing_ok=True)
                fallback_to_master(work)
                stats["fallback"] += 1
                print("display fallback for post #" + post_id + ": derivative exceeds 4 MiB")
                continue

            work.update(
                display_url=rel,
                display_variant=DERIVED_VARIANT,
                display_mime_type="image/webp",
                display_width=display_width,
                display_height=display_height,
                display_file_size=size,
                display_sha256=sha256_file(target),
                display_source_sha256=work["sha256"],
                display_generated_at=now_iso(),
            )
            referenced.add(rel)
            stats["derived"] += 1
            stats["display_bytes"] += size
            print(
                "display derivative #" + post_id + ": "
                + str(display_width) + "x" + str(display_height) + ", "
                + str(round(size / 1024)) + " KiB"
            )

    for stale in (DOCS_ROOT / "assets" / "artists").glob("*/*.display.webp"):
        rel = stale.relative_to(DOCS_ROOT).as_posix()
        if rel not in referenced:
            stale.unlink()
            print("removed stale display derivative " + rel)

    manifest["display_policy"] = DISPLAY_POLICY
    manifest["display_updated_at"] = now_iso()
    temp_manifest = MANIFEST_PATH.with_name(MANIFEST_PATH.name + ".tmp")
    temp_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp_manifest, MANIFEST_PATH)

    print(
        "Display derivatives ready: "
        + str(stats["derived"]) + " generated, "
        + str(stats["skipped"]) + " up to date, "
        + str(stats["fallback"]) + " master fallbacks, "
        + str(round(stats["display_bytes"] / 1024 / 1024, 2)) + " MiB total."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
