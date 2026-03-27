from __future__ import annotations

import unittest

from agent_usage_cli.cli import WatchSnapshotBuilder, build_parser
from agent_usage_cli.models import ProviderReport


class CliParserTests(unittest.TestCase):
    def test_short_watch_flag(self) -> None:
        args = build_parser().parse_args(["-w"])
        self.assertTrue(args.watch)
        self.assertEqual(args.interval, 1)

    def test_short_pretty_and_interval_flags(self) -> None:
        args = build_parser().parse_args(["claude", "-p", "-i", "3", "-v"])
        self.assertEqual(args.provider, "claude")
        self.assertTrue(args.pretty)
        self.assertEqual(args.interval, 3)
        self.assertTrue(args.verbose)


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
