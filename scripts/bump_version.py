from __future__ import annotations

import argparse
import re
from pathlib import Path

VERSION_FILE = Path("version.py")
VERSION_PATTERN = re.compile(r'__version__ = "(\d+)\.(\d+)\.(\d+)"')


def bump_version(current: str, bump: str) -> str:
    major, minor, patch = map(int, current.split("."))
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Bump the app version.")
    parser.add_argument("--dry-run", action="store_true", help="Print without writing")
    parser.add_argument("bump", choices=("patch", "minor", "major"))
    args = parser.parse_args()

    text = VERSION_FILE.read_text()
    match = VERSION_PATTERN.search(text)
    if match is None:
        raise SystemExit(f"Could not find __version__ in {VERSION_FILE}")

    new_version = bump_version(".".join(match.groups()), args.bump)
    if not args.dry_run:
        VERSION_FILE.write_text(
            VERSION_PATTERN.sub(f'__version__ = "{new_version}"', text)
        )
    print(new_version)


if __name__ == "__main__":
    main()
