from __future__ import annotations

import contextlib
import io
import unittest

from agent_usage_cli import __version__
from agent_usage_cli.cli import WatchSnapshotBuilder, build_parser, main
from agent_usage_cli.models import ProviderReport


class CliParserTests(unittest.TestCase):
    def test_short_watch_flag(self) -> None:
        args = build_parser().parse_args(["-w"])
        self.assertTrue(args.watch)
        self.assertEqual(args.interval, 1)

    def test_short_pretty_and_interval_flags(self) -> None:
        args = build_parser().parse_args(["claude", "-p", "-i", "3", "--verbose"])
        self.assertEqual(args.provider, "claude")
        self.assertTrue(args.pretty)
        self.assertEqual(args.interval, 3)
        self.assertTrue(args.verbose)

    def test_version_flag_prints_version_and_watch_hint(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(["-v"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(
            stdout.getvalue(),
            f"au {__version__}\nHint: run `au -w` for the live dashboard.\n",
        )


class WatchSnapshotBuilderTests(unittest.TestCase):
    def test_reuses_slow_provider_until_ttl_expires(self) -> None:
        clock_values = iter([0.0, 0.5, 1.1, 10.2])
        calls = {"codex": 0, "claude": 0, "cursor": 0}

        def detector(provider_id: str):
            def _run(_ctx) -> ProviderReport:
                calls[provider_id] += 1
                return ProviderReport(
                    id=provider_id,
                    label=provider_id.title(),
                    auth="logged_in",
                )

            return _run

        builder = WatchSnapshotBuilder(
            "all",
            clock=lambda: next(clock_values),
            ttl_by_provider={"codex": 1.0, "claude": 1.0, "cursor": 10.0},
            detector_by_provider={
                "codex": detector("codex"),
                "claude": detector("claude"),
                "cursor": detector("cursor"),
            },
        )

        builder()
        builder()
        builder()
        builder()

        self.assertEqual(calls["codex"], 3)
        self.assertEqual(calls["claude"], 3)
        self.assertEqual(calls["cursor"], 2)


if __name__ == "__main__":
    unittest.main()
