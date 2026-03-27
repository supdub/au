from __future__ import annotations

from pathlib import Path
import tomllib
import unittest

from agent_usage_cli import __version__
from agent_usage_cli.versioning import normalize_release_version, release_tag_matches_version


ROOT = Path(__file__).resolve().parent.parent


class VersioningTests(unittest.TestCase):
    def test_normalize_release_version_trims_trailing_zero_segments(self) -> None:
        self.assertEqual(normalize_release_version("v0.1.0"), "0.1")
        self.assertEqual(normalize_release_version("0.1.0"), "0.1")
        self.assertEqual(normalize_release_version("0.1.1"), "0.1.1")

    def test_release_tag_matches_version_for_equivalent_versions(self) -> None:
        self.assertTrue(release_tag_matches_version("v0.1", "0.1.0"))
        self.assertTrue(release_tag_matches_version("v0.1.1", "0.1.1"))
        self.assertFalse(release_tag_matches_version("v0.1.2", "0.1.1"))

    def test_pyproject_version_matches_package_version(self) -> None:
        with (ROOT / "pyproject.toml").open("rb") as fh:
            pyproject = tomllib.load(fh)
        self.assertEqual(pyproject["project"]["version"], __version__)


if __name__ == "__main__":
    unittest.main()
