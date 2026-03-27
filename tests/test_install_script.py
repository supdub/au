from __future__ import annotations

import os
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parent.parent


class InstallScriptTests(unittest.TestCase):
    def run_script(self, *, version: str, os_name: str, arch: str) -> str:
        env = os.environ.copy()
        env.update(
            {
                "AU_VERSION": version,
                "AU_OS": os_name,
                "AU_ARCH": arch,
                "AU_SKIP_ASSET_PROBE": "1",
            }
        )
        proc = subprocess.run(
            ["bash", "install.sh", "--print-download-url"],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout.strip()

    def test_linux_x86_64_uses_native_release_asset(self) -> None:
        self.assertEqual(
            self.run_script(version="latest", os_name="Linux", arch="x86_64"),
            "https://github.com/supdub/au/releases/latest/download/au-linux-x86_64",
        )

    def test_macos_arm64_uses_versioned_native_release_asset(self) -> None:
        self.assertEqual(
            self.run_script(version="v0.1.1", os_name="Darwin", arch="arm64"),
            "https://github.com/supdub/au/releases/download/v0.1.1/au-macos-arm64",
        )

    def test_unknown_platform_falls_back_to_portable_artifact(self) -> None:
        self.assertEqual(
            self.run_script(version="v0.1.1", os_name="Linux", arch="riscv64"),
            "https://github.com/supdub/au/releases/download/v0.1.1/au",
        )


if __name__ == "__main__":
    unittest.main()
