#!/usr/bin/env python3
from __future__ import annotations

import shutil
import tempfile
import zipapp
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"


def main() -> int:
    DIST.mkdir(exist_ok=True)
    target = DIST / "au"

    with tempfile.TemporaryDirectory(prefix="au-zipapp-") as tmp_dir:
        staging = Path(tmp_dir)
        shutil.copytree(ROOT / "agent_usage_cli", staging / "agent_usage_cli")
        (staging / "__main__.py").write_text(
            "from agent_usage_cli.cli import main\n"
            "raise SystemExit(main())\n",
            encoding="utf-8",
        )
        zipapp.create_archive(
            staging,
            target=target,
            interpreter="/usr/bin/env python3",
            compressed=True,
        )
    target.chmod(0o755)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
