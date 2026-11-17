#!/usr/bin/env python3
"""Compute an 8x8 difference hash (dHash) for one or more local images.

The artwork sync script downloads small Danbooru previews and calls this helper
to tell apart genuinely different works from variants (差分) of the same one.
Nothing produced here is committed to the repository.

Usage:
    python scripts/image-signature.py path/to/a.jpg [path/to/b.png ...]

Output: a JSON array of {path, hash, error} records, one per input file.
"""

import json
import sys

from PIL import Image

HASH_SIZE = 8


def difference_hash(path):
    with Image.open(path) as image:
        # A 9x8 grayscale thumbnail keeps one extra column so every pixel can be
        # compared with its right-hand neighbour.
        thumbnail = image.convert("L").resize(
            (HASH_SIZE + 1, HASH_SIZE), Image.Resampling.LANCZOS
        )
        pixels = thumbnail.tobytes()
    bits = 0
    for row in range(HASH_SIZE):
        offset = row * (HASH_SIZE + 1)
        for column in range(HASH_SIZE):
            bits = (bits << 1) | (1 if pixels[offset + column] > pixels[offset + column + 1] else 0)
    return format(bits, "016x")


def main(argv):
    results = []
    for path in argv:
        try:
            results.append({"path": path, "hash": difference_hash(path)})
        except Exception as error:  # noqa: BLE001 - report per-file failures to Node
            results.append({"path": path, "hash": None, "error": str(error)})
    json.dump(results, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
