from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import time
from typing import Callable, Sequence

from agent_usage_cli import __version__
from agent_usage_cli.detectors import (
    PROVIDER_ORDER,
    RuntimeContext,
    collect_reports,
    default_context,
    detect_claude,
    detect_codex,
    detect_cursor,
)
from agent_usage_cli.models import ProviderReport
from agent_usage_cli.render import watch_loop
from agent_usage_cli.utils import utc_now_iso


WATCH_PROVIDER_TTLS = {
    "codex": 1.0,
    "claude": 15.0,
    "cursor": 10.0,
}

DETECTOR_BY_PROVIDER = {
    "codex": detect_codex,
    "claude": detect_claude,
    "cursor": detect_cursor,
}

WATCH_DETECTOR_BY_PROVIDER = {
    "codex": detect_codex,
    "claude": lambda ctx: detect_claude(
        RuntimeContext(
            home=ctx.home,
            env={**ctx.env, "AU_ENABLE_CLAUDE_INSIGHTS": "1"},
            now=ctx.now,
        )
    ),
    "cursor": detect_cursor,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="au",
        description="Inspect local auth state and usage context for Codex, Claude Code, and Cursor Agent.",
        epilog=(
            "Examples:\n"
            "  au\n"
            "  au codex\n"
            "  au -w\n"
            "  au -w -i 2\n"
            "  au all --pretty\n"
            "  au claude | jq '.providers[0].usage.metrics.total_tokens'\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "provider",
        nargs="?",
        default="all",
        choices=("all",) + PROVIDER_ORDER,
        help="Provider to inspect. Defaults to all.",
    )
    parser.add_argument(
        "-w",
        "--watch",
        action="store_true",
        help="Refresh a colorful terminal view instead of printing JSON once.",
    )
    parser.add_argument(
        "-i",
        "--interval",
        type=int,
        default=1,
        help="Watch refresh interval in seconds. Default: 1.",
    )
    parser.add_argument(
        "-p",
        "--pretty",
        action="store_true",
        help="Pretty-print JSON. Default JSON is compact for automation.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include detector evidence such as file paths and raw local signals.",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="store_true",
        help="Print the installed version and a hint for watch mode.",
    )
    return parser


def make_snapshot(provider: str, verbose: bool = False) -> dict[str, object]:
    ctx = default_context()
    provider_ids = list(PROVIDER_ORDER if provider == "all" else (provider,))
    providers = [report.to_dict() for report in collect_reports(provider_ids, ctx)]
    if not verbose:
        for provider_data in providers:
            provider_data.pop("evidence", None)
    return {
        "generated_at": utc_now_iso(),
        "tool_version": __version__,
        "providers": providers,
    }


class WatchSnapshotBuilder:
    def __init__(
        self,
        provider: str,
        *,
        verbose: bool = False,
        clock=time.monotonic,
        ttl_by_provider: dict[str, float] | None = None,
        detector_by_provider: dict[str, Callable[..., ProviderReport]] | None = None,
    ) -> None:
        self.provider_ids = list(PROVIDER_ORDER if provider == "all" else (provider,))
        self.verbose = verbose
        self.clock = clock
        self.ttl_by_provider = ttl_by_provider or WATCH_PROVIDER_TTLS
        self.detector_by_provider = detector_by_provider or DETECTOR_BY_PROVIDER
        self.cached_provider_data: dict[str, dict[str, object]] = {}
        self.next_refresh_at: dict[str, float] = {}

    def __call__(self) -> dict[str, object]:
        now = self.clock()
        due_provider_ids = [
            provider_id
            for provider_id in self.provider_ids
            if provider_id not in self.cached_provider_data or now >= self.next_refresh_at.get(provider_id, 0.0)
        ]
        if due_provider_ids:
            for provider_id, report in _detect_reports_in_parallel(
                due_provider_ids,
                detector_by_provider=self.detector_by_provider,
            ).items():
                provider_data = report.to_dict()
                if not self.verbose:
                    provider_data.pop("evidence", None)
                self.cached_provider_data[provider_id] = provider_data
                self.next_refresh_at[provider_id] = now + self.ttl_by_provider.get(provider_id, 1.0)
        providers = [self.cached_provider_data[provider_id] for provider_id in self.provider_ids]
        return {
            "generated_at": utc_now_iso(),
            "tool_version": __version__,
            "providers": providers,
        }


def _detect_reports_in_parallel(
    provider_ids: list[str],
    *,
    detector_by_provider: dict[str, Callable[..., ProviderReport]] | None = None,
) -> dict[str, ProviderReport]:
    detectors = detector_by_provider or DETECTOR_BY_PROVIDER
    if len(provider_ids) == 1:
        provider_id = provider_ids[0]
        return {provider_id: detectors[provider_id](default_context())}

    with ThreadPoolExecutor(max_workers=len(provider_ids)) as executor:
        futures = {
            provider_id: executor.submit(detectors[provider_id], default_context())
            for provider_id in provider_ids
        }
        return {provider_id: future.result() for provider_id, future in futures.items()}


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(f"au {__version__}")
        print("Hint: run `au -w` for the live dashboard.")
        return 0

    if args.interval < 1:
        parser.error("--interval must be >= 1")

    if args.watch:
        return watch_loop(
            WatchSnapshotBuilder(
                args.provider,
                verbose=args.verbose,
                detector_by_provider=WATCH_DETECTOR_BY_PROVIDER,
            ),
            args.interval,
        )

    snapshot = make_snapshot(args.provider, verbose=args.verbose)
    if args.pretty:
        print(json.dumps(snapshot, indent=2, sort_keys=False))
    else:
        print(json.dumps(snapshot, separators=(",", ":"), sort_keys=False))
    return 0
