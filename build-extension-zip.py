#!/usr/bin/env python3
"""build-extension-zip.py — build the EEZ Studio extension release zip.

Cross-platform (Windows/macOS/Linux) replacement for a per-repo shell/batch
script. Reads the version from package.json (single source of truth, so
there's no separate version string to remember to bump here), and always
writes package.json etc. at the zip ROOT — a nested folder there is exactly
what causes EEZ Studio's installer to fail with "Failed to read description".

Usage: python3 build-extension-zip.py
"""

import json
import sys
import zipfile
from pathlib import Path

# The only thing that differs between repos in this instrument family --
# copy this script verbatim into a sibling repo and edit only this line.
ZIP_NAME_PREFIX = "ea-ps2000-series"

REPO_ROOT = Path(__file__).resolve().parent

# Exactly what an EEZ Studio extension zip is made of -- deliberately NOT
# "every file in the directory", since for repos where these files live at
# the repo root (not an eezstudio/ subfolder) that would also sweep up
# README.md, .gitignore, this script itself, etc.
EXTENSION_GLOBS = ["package.json", "*.idf", "*.sdl", "image.*"]


def find_extension_dir() -> Path:
    """Locate the folder holding package.json + .idf/.sdl/image.png --
    either the repo root itself, or an eezstudio/ subfolder (this repo's
    layout, since it also ships a separate bridge/driver at the root)."""
    for candidate in (REPO_ROOT, REPO_ROOT / "eezstudio"):
        pkg = candidate / "package.json"
        if pkg.is_file():
            data = json.loads(pkg.read_text(encoding="utf-8"))
            if "eez-studio" in data:
                return candidate
    sys.exit(
        "ERROR: no package.json with an \"eez-studio\" key found in "
        f"{REPO_ROOT} or {REPO_ROOT / 'eezstudio'}"
    )


def main() -> None:
    src = find_extension_dir()
    package = json.loads((src / "package.json").read_text(encoding="utf-8"))
    version = package["version"]

    files = sorted({p for pattern in EXTENSION_GLOBS for p in src.glob(pattern)})
    if not files:
        sys.exit(f"ERROR: no files found in {src}")

    out_path = REPO_ROOT / f"{ZIP_NAME_PREFIX}-{version}.zip"
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            # arcname=f.name (not the full path) keeps everything flat at
            # the zip root -- never nested under a nested build folder.
            zf.write(f, arcname=f.name)

    print(f"Created: {out_path}")
    print(f"  {len(files)} file(s): {', '.join(f.name for f in files)}")
    print()
    print("In EEZ Studio: Extensions Manager -> ☰ menu -> Install Extension")


if __name__ == "__main__":
    main()
