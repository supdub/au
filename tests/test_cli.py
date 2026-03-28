from __future__ import annotations

import contextlib
import io
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from agent_usage_cli import __version__
from agent_usage_cli.cli import DETECTOR_BY_PROVIDER, WatchSnapshotBuilder, build_parser, main, watch_detector_by_provider
from agent_usage_cli.detectors import RuntimeContext
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
        self.assertFalse(args.claude_insights)
        self.assertTrue(args.claude_web_usage)

    def test_claude_insights_flag_is_explicit_opt_in(self) -> None:
        args = build_parser().parse_args(["claude", "-w", "--claude-insights"])
        self.assertTrue(args.watch)
        self.assertTrue(args.claude_insights)

    def test_claude_web_usage_is_enabled_by_default(self) -> None:
        args = build_parser().parse_args(["claude"])
        self.assertTrue(args.claude_web_usage)

    def test_claude_web_usage_can_be_disabled_explicitly(self) -> None:
        args = build_parser().parse_args(["claude", "--no-claude-web-usage"])
        self.assertFalse(args.claude_web_usage)

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
    def test_claude_insights_detector_is_opt_in(self) -> None:
        ctx = RuntimeContext(
            home=Path("/tmp"),
            env={},
            now=datetime(2026, 3, 28, tzinfo=timezone.utc),
        )
        with patch("agent_usage_cli.cli.detect_claude") as detect:
            detect.return_value = ProviderReport(id="claude", label="Claude", auth="logged_in")
            watch_detector_by_provider(True, False)["claude"](ctx)
        detect.assert_called_once()
        called_ctx = detect.call_args.args[0]
        self.assertEqual(called_ctx.env["AU_ENABLE_CLAUDE_INSIGHTS"], "1")

    def test_claude_web_usage_detector_is_default(self) -> None:
        self.assertIs(
            watch_detector_by_provider(False, True)["claude"],
            DETECTOR_BY_PROVIDER["claude"],
        )

    def test_claude_web_usage_detector_can_be_disabled(self) -> None:
        ctx = RuntimeContext(
            home=Path("/tmp"),
            env={},
            now=datetime(2026, 3, 28, tzinfo=timezone.utc),
        )
        with patch("agent_usage_cli.cli.detect_claude") as detect:
            detect.return_value = ProviderReport(id="claude", label="Claude", auth="logged_in")
            watch_detector_by_provider(False, False)["claude"](ctx)
        detect.assert_called_once()
        called_ctx = detect.call_args.args[0]
        self.assertEqual(called_ctx.env["AU_DISABLE_CLAUDE_WEB_USAGE"], "1")

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
