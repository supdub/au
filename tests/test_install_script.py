from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parent.parent


class InstallScriptTests(unittest.TestCase):
    def make_executable(self, path: Path, contents: str) -> None:
        path.write_text(contents, encoding="utf-8")
        path.chmod(0o755)

    def make_zip_archive(self, path: Path, files: dict[str, str]) -> None:
        with zipfile.ZipFile(path, "w") as archive:
            for name, contents in files.items():
                archive.writestr(name, contents)

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

    def run_install_with_fake_assets(
        self,
        assets: dict[str, str],
        *,
        version: str = "v0.1.1",
        archives: dict[str, dict[str, str]] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], str]:
        with tempfile.TemporaryDirectory() as tmpdir_name:
            tmpdir = Path(tmpdir_name)
            asset_dir = tmpdir / "assets"
            fake_bin_dir = tmpdir / "fake-bin"
            bin_dir = tmpdir / "bin"
            asset_dir.mkdir()
            fake_bin_dir.mkdir()

            for name, contents in assets.items():
                self.make_executable(asset_dir / name, contents)

            for name, files in (archives or {}).items():
                self.make_zip_archive(asset_dir / name, files)

            self.make_executable(
                fake_bin_dir / "curl",
                """#!/usr/bin/env python3
import os
import shutil
import sys

args = sys.argv[1:]
output = None
url = None
i = 0

while i < len(args):
    arg = args[i]
    if arg == "-o":
        output = args[i + 1]
        i += 2
        continue
    if arg.startswith("-"):
        i += 1
        continue
    url = arg
    i += 1

if output is None or url is None:
    sys.exit(2)

name = url.rstrip("/").rsplit("/", 1)[-1]
src = os.path.join(os.environ["FAKE_ASSET_DIR"], name)
shutil.copyfile(src, output)
""",
            )

            env = os.environ.copy()
            env.update(
                {
                    "AU_VERSION": version,
                    "AU_OS": "Linux",
                    "AU_ARCH": "x86_64",
                    "AU_SKIP_ASSET_PROBE": "1",
                    "AU_BIN_DIR": str(bin_dir),
                    "FAKE_ASSET_DIR": str(asset_dir),
                    "PATH": f"{fake_bin_dir}:{env['PATH']}",
                }
            )

            proc = subprocess.run(
                ["bash", "install.sh"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
            )

            installed_output = ""
            installed_path = bin_dir / "au"
            if installed_path.exists():
                installed_proc = subprocess.run(
                    [str(installed_path)],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                installed_output = installed_proc.stdout.strip()

            return proc, installed_output

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

    def test_install_falls_back_to_portable_asset_on_glibc_error(self) -> None:
        proc, installed_output = self.run_install_with_fake_assets(
            {
                "au-linux-x86_64": """#!/usr/bin/env bash
echo "[PYI-750009:ERROR] Failed to load Python shared library '/tmp/libpython3.12.so.1.0': /lib/x86_64-linux-gnu/libm.so.6: GLIBC_2.38 not found" >&2
exit 1
""",
                "au": """#!/usr/bin/env bash
echo portable-asset
""",
            }
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("falling back to the portable Python artifact", proc.stderr)
        self.assertEqual(installed_output, "portable-asset")

    def test_install_keeps_native_asset_when_validation_succeeds(self) -> None:
        proc, installed_output = self.run_install_with_fake_assets(
            {
                "au-linux-x86_64": """#!/usr/bin/env bash
if [[ "${1:-}" == "-v" ]]; then
  echo native-version
  exit 0
fi
echo native-asset
""",
                "au": """#!/usr/bin/env bash
echo portable-asset
""",
            }
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("falling back to the portable Python artifact", proc.stderr)
        self.assertEqual(installed_output, "native-asset")

    def test_install_builds_from_source_when_latest_portable_artifact_is_python_incompatible(self) -> None:
        proc, installed_output = self.run_install_with_fake_assets(
            {
                "au-linux-x86_64": """#!/usr/bin/env bash
echo "[PYI-750009:ERROR] Failed to load Python shared library '/tmp/libpython3.12.so.1.0': /lib/x86_64-linux-gnu/libm.so.6: GLIBC_2.38 not found" >&2
exit 1
""",
                "au": """#!/usr/bin/env bash
echo "Traceback (most recent call last):" >&2
echo "ModuleNotFoundError: No module named 'tomllib'" >&2
exit 1
""",
            },
            version="latest",
            archives={
                "main.zip": {
                    "au-main/scripts/build_zipapp.py": """from pathlib import Path

root = Path(__file__).resolve().parents[1]
dist = root / "dist"
dist.mkdir(exist_ok=True)
(dist / "au").write_text("#!/usr/bin/env bash\\necho source-built\\n", encoding="utf-8")
""",
                }
            },
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("falling back to the portable Python artifact", proc.stderr)
        self.assertIn("building from the main branch source archive instead", proc.stderr)
        self.assertEqual(installed_output, "source-built")


if __name__ == "__main__":
    unittest.main()
