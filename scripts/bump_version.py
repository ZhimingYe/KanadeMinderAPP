#!/usr/bin/env python3
"""Bump the version of KanadeMinder.

Usage:
    python scripts/bump_version.py patch        # 0.1.0 → 0.1.1  (default)
    python scripts/bump_version.py minor        # 0.1.0 → 0.2.0
    python scripts/bump_version.py major        # 0.1.0 → 1.0.0
    python scripts/bump_version.py --dry-run    # show new version, don't write
    python scripts/bump_version.py minor --no-tag   # skip git commit/tag
    python scripts/bump_version.py 1.2.3        # set an explicit version

Updates:
    pyproject.toml
    src/kanademinder/__init__.py
    Makefile

Then creates a git commit and tag (v<new_version>) unless --no-tag is passed.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
PYPROJECT = ROOT / "pyproject.toml"
INIT = ROOT / "src" / "kanademinder" / "__init__.py"
MAKEFILE = ROOT / "Makefile"


def read_current_version() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        sys.exit(f"error: could not find version in {PYPROJECT}")
    return m.group(1)


def parse_semver(version: str) -> tuple[int, int, int]:
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if not m:
        sys.exit(f"error: '{version}' is not a valid semver string (expected X.Y.Z)")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def bump(version: str, part: str) -> str:
    major, minor, patch = parse_semver(version)
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    # explicit version string
    parse_semver(part)  # validate
    return part


def update_file(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    new_text, n = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if n == 0:
        sys.exit(f"error: pattern not found in {path}")
    path.write_text(new_text, encoding="utf-8")


def git(*args: str) -> None:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"error: git {' '.join(args)}\n{result.stderr.strip()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "part",
        nargs="?",
        default="patch",
        help="'major', 'minor', 'patch', or an explicit version like '1.2.3' (default: patch)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print what would happen without writing anything")
    parser.add_argument("--no-tag", action="store_true", help="Skip the git commit and tag")
    args = parser.parse_args()

    current = read_current_version()
    new = bump(current, args.part)

    print(f"  current: {current}")
    print(f"      new: {new}")

    if args.dry_run:
        print("(dry run — no files written)")
        return

    # Update pyproject.toml
    update_file(PYPROJECT, r'^(version\s*=\s*)"[^"]+"', rf'\g<1>"{new}"')
    print(f"  updated: {PYPROJECT.relative_to(ROOT)}")

    # Update __init__.py
    update_file(INIT, r'^(__version__\s*=\s*)"[^"]+"', rf'\g<1>"{new}"')
    print(f"  updated: {INIT.relative_to(ROOT)}")

    # Update Makefile
    update_file(MAKEFILE, r'^(VERSION\s*:=\s*)\S+', rf'\g<1>{new}')
    print(f"  updated: {MAKEFILE.relative_to(ROOT)}")

    if args.no_tag:
        print("(skipped git commit/tag)")
        return

    # Commit and tag
    git("add", str(PYPROJECT.relative_to(ROOT)), str(INIT.relative_to(ROOT)), str(MAKEFILE.relative_to(ROOT)))
    git("commit", "-m", f"chore: bump version to {new}")
    git("tag", f"v{new}")
    print(f"  git tag: v{new}")
    print()
    print(f"To push: git push && git push origin v{new}")


if __name__ == "__main__":
    main()
