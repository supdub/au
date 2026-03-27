#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_usage_cli import __version__
from agent_usage_cli.versioning import release_tag_matches_version


def main() -> int:
    tag_version = os.environ["TAG_VERSION"]
    if not release_tag_matches_version(tag_version, __version__):
        raise SystemExit(
            f"Tag version {tag_version.removeprefix('v')!r} does not match package version {__version__!r}"
        )
    print(f"release tag {tag_version} matches package version {__version__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
