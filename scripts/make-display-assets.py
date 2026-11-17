#!/usr/bin/env python3
"""Convert staged source files into the only archived artwork files: 1600 px WebP.

The repository no longer stores original artwork files. `sync-artworks.mjs`
downloads each selected post into a temporary staging directory and records the
source checksum in the manifest; this script converts those staged files into
`assets/artists/<artist_id>/<post_id>.display.webp`, updates the manifest with
the derivative metadata, and deletes the staged source.

Usage:
    python scripts/make-display-assets.py                # convert what is staged
    python scripts/make-display-assets.py --force        # rebuild every derivative
    python scripts/make-display-assets.py --staging DIR  # custom staging directory

When nothing is staged (for example a manifest-only change), existing display
files are verified and reused.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover - dependency hint
    sys.stderr.write(
        "Pillow is required for display derivatives.\n"
        "Install it with: python -m pip install 'Pillow>=10'\n"
    )
    raise SystemExit(2)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "artworks.json"
DOCS_ROOT = ROOT / "docs"
STAGING_ROOT = Path(
    os.environ.get("ATLAS_STAGING", str(Path(tempfile.gettempdir()) / "artist-atlas-staging"))
)
MAX_EDGE = 1600
WEBP_QUALITY = 85
MAX_DISPLAY_BYTES = 4 * 1024 * 1024
DERIVED_VARIANT = "derived_1600_webp"
DISPLAY_POLICY = (
    "The grid loads a 1600 px WebP display derivative (quality 85) generated from the "
    "Danbooru source file. Source files are converted in a temporary staging directory "
    "and are not committed to this repository."
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def staging_path(staging_root: Path, artist_id: str, work: dict) -> Path:
    return staging_root / artist_id / (str(work["post_id"]) + "." + str(work["source_file_ext"]))


def is_current(work: dict, target: Path, force: bool) -> bool:
    if force or work.get("display_variant") != DERIVED_VARIANT:
        return False
    if work.get("display_source_sha256") != work.get("source_sha256"):
        return False
    if not target.is_file() or target.stat().st_size != work.get("display_file_size"):
        return False
    return sha256_file(target) == work.get("display_sha256")


def build_derivative(source: Path, target: Path) -> tuple[int, int]:
    with Image.open(source) as image:
        if getattr(image, "n_frames", 1) > 1:
            raise ValueError("animated source is not supported")
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
    args = sys.argv[1:]
    force = "--force" in args
    staging_root = STAGING_ROOT
    if "--staging" in args:
        staging_root = Path(args[args.index("--staging") + 1])
    only_artist = args[args.index("--only") + 1] if "--only" in args else None

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest.get("status") != "ready" or not isinstance(manifest.get("artists"), list):
        sys.stderr.write("data/artworks.json is not a ready archive; run the sync script first.\n")
        return 1

    stats = {"derived": 0, "skipped": 0, "display_bytes": 0}
    referenced = set()
    missing = []

    for record in manifest["artists"]:
        artist_id = str(record["artist_id"])
        if only_artist and artist_id != str(only_artist):
            continue
        for work in record["artworks"]:
            post_id = str(work["post_id"])
            rel = "assets/artists/" + artist_id + "/" + post_id + ".display.webp"
            target = DOCS_ROOT / rel

            if is_current(work, target, force):
                stats["skipped"] += 1
                stats["display_bytes"] += target.stat().st_size
                referenced.add(rel)
                continue

            source = staging_path(staging_root, artist_id, work)
            if not source.is_file():
                missing.append("#" + post_id + " (" + rel + ")")
                continue

            display_width, display_height = build_derivative(source, target)
            size = target.stat().st_size
            if size > MAX_DISPLAY_BYTES:
                target.unlink(missing_ok=True)
                missing.append("#" + post_id + " (derivative exceeds 4 MiB)")
                continue

            work.update(
                display_url=rel,
                display_variant=DERIVED_VARIANT,
                display_mime_type="image/webp",
                display_width=display_width,
                display_height=display_height,
                display_file_size=size,
                display_sha256=sha256_file(target),
                display_source_sha256=work["source_sha256"],
                display_generated_at=now_iso(),
            )
            source.unlink(missing_ok=True)
            referenced.add(rel)
            stats["derived"] += 1
            stats["display_bytes"] += size

    if missing:
        sys.stderr.write(
            "Missing staged sources for " + str(len(missing)) + " work(s):\n  "
            + "\n  ".join(missing[:20]) + "\n"
        )
        return 1

    if not only_artist:
        for stale in (DOCS_ROOT / "assets" / "artists").glob("*/*.display.webp"):
            rel = stale.relative_to(DOCS_ROOT).as_posix()
            if rel not in referenced:
                stale.unlink()
                print("removed stale display derivative " + rel)

        # Older archives stored source masters next to the derivatives; the grid
        # only needs the WebP copies.
        for stale in (DOCS_ROOT / "assets" / "artists").glob("*/*"):
            if stale.is_file() and stale.suffix.lower() != ".webp":
                stale.unlink()
                print("removed archived source file " + stale.relative_to(DOCS_ROOT).as_posix())

    manifest["display_policy"] = DISPLAY_POLICY
    manifest["display_updated_at"] = now_iso()
    temp_manifest = MANIFEST_PATH.with_name(MANIFEST_PATH.name + ".tmp")
    temp_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temp_manifest, MANIFEST_PATH)

    print(
        "Display derivatives ready: "
        + str(stats["derived"]) + " generated, "
        + str(stats["skipped"]) + " up to date, "
        + str(round(stats["display_bytes"] / 1024 / 1024, 2)) + " MiB total."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
