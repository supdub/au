from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from typing import Any


RESET = "\033[0m"
BOLD = "\033[1m"
ENTER_ALT_SCREEN = "\033[?1049h"
EXIT_ALT_SCREEN = "\033[?1049l"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
CLEAR_SCREEN_HOME = "\033[2J\033[H"

PALETTE = {
    "title": "\033[38;5;219m",
    "sub": "\033[38;5;117m",
    "ok": "\033[38;5;121m",
    "warn": "\033[38;5;221m",
    "bad": "\033[38;5;203m",
    "info": "\033[38;5;153m",
    "muted": "\033[38;5;245m",
    "accent": "\033[38;5;87m",
}


def render_watch(snapshot: dict[str, Any], interval: int) -> None:
    width = _terminal_width()
    providers = snapshot["providers"]
    logged_in_count = sum(1 for provider in providers if provider.get("auth") == "logged_in")
    lines: list[str] = []

    lines.append(
        f"{PALETTE['title']}{BOLD}au{RESET}  "
        f"{PALETTE['sub']}watch{RESET}  "
        f"{PALETTE['muted']}refresh {interval}s{RESET}  "
        f"{PALETTE['info']}{logged_in_count}/{len(providers)} ready{RESET}"
    )
    lines.append(f"{PALETTE['muted']}Updated {_format_timestamp(snapshot['generated_at'])}{RESET}")
    lines.append("")

    for index, provider in enumerate(providers):
        lines.extend(_render_provider(provider, width))
        if index != len(providers) - 1:
            lines.append("")

    sys.stdout.write(CLEAR_SCREEN_HOME)
    sys.stdout.write("\n".join(lines).rstrip() + "\n")
    sys.stdout.flush()


def watch_loop(build_snapshot, interval: int) -> int:
    last_signature: str | None = None
    interactive = _is_interactive_stream(sys.stdout)
    next_tick = time.monotonic()
    try:
        if interactive:
            sys.stdout.write(_enter_watch_terminal())
            sys.stdout.flush()
        while True:
            snapshot = build_snapshot()
            signature = _snapshot_signature(snapshot)
            if _should_render_frame(interactive=interactive, signature=signature, last_signature=last_signature):
                render_watch(snapshot, interval)
            last_signature = signature
            now = time.monotonic()
            next_tick = _advance_next_tick(next_tick, now, interval)
            sleep_for = next_tick - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)
    except KeyboardInterrupt:
        return 0
    finally:
        if interactive:
            sys.stdout.write(_exit_watch_terminal())
            sys.stdout.flush()


def _render_provider(provider: dict[str, Any], width: int) -> list[str]:
    usage = provider.get("usage") or {}
    windows = usage.get("windows") or {}
    metrics = usage.get("metrics") or {}
    session = usage.get("session") or {}
    account = provider.get("account") or {}
    bar_width = max(12, min(24, width - 44))

    lines = [
        f"{PALETTE['accent']}{'=' * min(width, 88)}{RESET}",
        _provider_title(provider),
    ]

    if provider.get("auth") != "logged_in":
        for action in provider.get("actions") or []:
            lines.append(_label_line("Login", action))
        for warning in provider.get("warnings") or []:
            lines.append(_warning_line(warning))
        if usage.get("summary"):
            lines.append(_label_line("Status", usage["summary"]))
        return lines

    provider_id = provider["id"]
    if provider_id == "codex":
        lines.extend(_render_codex(metrics, windows, session, bar_width))
    elif provider_id == "claude":
        lines.extend(_render_claude(provider, metrics, windows, session, account, bar_width))
    elif provider_id == "cursor":
        lines.extend(_render_cursor(provider, metrics, account))
    else:
        if usage.get("summary"):
            lines.append(_label_line("Status", usage["summary"]))

    return lines


def _provider_title(provider: dict[str, Any]) -> str:
    auth = provider.get("auth")
    state_color = PALETTE["warn"]
    if auth == "logged_in":
        state_color = PALETTE["ok"]
    elif auth == "login_required":
        state_color = PALETTE["bad"]

    bits = [
        f"{BOLD}{provider['label']}{RESET}",
        f"{state_color}{provider.get('auth', 'unknown')}{RESET}",
    ]
    if provider.get("mode"):
        bits.append(f"{PALETTE['info']}mode={_pretty_text(str(provider['mode']))}{RESET}")
    if provider.get("billing"):
        bits.append(f"{PALETTE['sub']}billing={_pretty_text(str(provider['billing']))}{RESET}")
    return "  ".join(bits)


def _render_codex(
    metrics: dict[str, Any],
    windows: dict[str, Any],
    session: dict[str, Any],
    bar_width: int,
) -> list[str]:
    lines: list[str] = []
    plan_type = session.get("plan_type")
    if plan_type:
        lines.append(_label_line("Plan", str(plan_type)))

    for name in ("primary", "secondary"):
        window = windows.get(name) or {}
        line = _quota_line(_window_title(window, name), window, bar_width)
        if line:
            lines.append(line)

    last_total = _coerce_number(metrics.get("last_total_tokens"))
    if last_total is not None:
        lines.append(_label_line("Last turn", f"{_compact_number(last_total)} tokens"))

    uncached = _uncached_codex_percent(metrics)
    if uncached is not None:
        lines.append(_label_line("Uncached", f"{uncached:.1f}% of last-turn input"))
    return lines


def _render_claude(
    provider: dict[str, Any],
    metrics: dict[str, Any],
    windows: dict[str, Any],
    session: dict[str, Any],
    account: dict[str, Any],
    bar_width: int,
) -> list[str]:
    lines: list[str] = []
    subscription = account.get("subscription_type")
    if subscription:
        lines.append(_label_line("Plan", str(subscription)))

    showed_window = False
    for name in ("primary", "secondary"):
        window = windows.get(name) or {}
        line = _quota_or_status_line(_window_title(window, name), window, bar_width)
        if line:
            showed_window = True
            lines.append(line)

    last_request = (session.get("last_request") or {}) if isinstance(session.get("last_request"), dict) else {}
    last_total = _coerce_number(last_request.get("total_tokens"))
    if last_total is not None:
        lines.append(_label_line("Last req", f"{_compact_number(last_total)} tokens"))

    fresh = _fresh_claude_percent(last_request)
    if fresh is not None:
        lines.append(_label_line("Fresh in", f"{fresh:.1f}% of prompt tokens"))

    if not showed_window:
        status = _claude_status(provider.get("warnings") or [])
        if status:
            lines.append(_label_line("Status", status))

    requests = _coerce_number(metrics.get("requests"))
    total_tokens = _coerce_number(metrics.get("total_tokens"))
    if requests is not None and total_tokens is not None:
        lines.append(_label_line("Session", f"{int(requests)} req / {_compact_number(total_tokens)} tokens"))
    return lines


def _render_cursor(provider: dict[str, Any], metrics: dict[str, Any], account: dict[str, Any]) -> list[str]:
    lines: list[str] = []

    plan_bits = []
    if account.get("subscription_type"):
        plan_bits.append(str(account["subscription_type"]))
    if provider.get("billing"):
        plan_bits.append(_pretty_text(str(provider["billing"])))
    if plan_bits:
        lines.append(_label_line("Plan", " ".join(plan_bits)))

    included = metrics.get("included_usage_dollars")
    if included not in (None, "", 0):
        lines.append(_label_line("Included", f"${included}"))

    credit = metrics.get("credit_dollars")
    if credit not in (None, "", 0):
        lines.append(_label_line("Credit", f"${credit}"))

    model = account.get("current_model")
    if model:
        lines.append(_label_line("Model", str(model)))

    lines.append(_label_line("Live usage", "unavailable from installed CLI"))
    return lines


def _quota_line(label: str, window: dict[str, Any], bar_width: int) -> str | None:
    used = _coerce_number(window.get("used_percent"))
    if used is None:
        return None
    remaining = max(0.0, min(100.0, 100.0 - used))
    reset_text = _format_epoch(window.get("resets_at"))
    return (
        f"{PALETTE['info']}{label:<10}{RESET}  "
        f"{_remaining_bar(remaining, bar_width)}  "
        f"{remaining:5.1f}% left"
        + (f"  reset {reset_text}" if reset_text else "")
    )


def _quota_or_status_line(label: str, window: dict[str, Any], bar_width: int) -> str | None:
    quota_line = _quota_line(label, window, bar_width)
    if quota_line:
        return quota_line

    status = _pretty_text(str(window.get("status"))) if window.get("status") else None
    reset_text = _format_epoch(window.get("resets_at"))
    parts: list[str] = []
    if status:
        parts.append(status)
    if reset_text:
        parts.append(f"reset {reset_text}")
    if not parts:
        return None
    return f"{PALETTE['info']}{label:<10}{RESET}  " + "  ".join(parts)


def _remaining_bar(remaining: float, width: int) -> str:
    width = max(8, width)
    filled = int(round((remaining / 100.0) * width))
    empty = width - filled
    if remaining >= 60:
        color = PALETTE["ok"]
    elif remaining >= 30:
        color = PALETTE["warn"]
    else:
        color = PALETTE["bad"]
    return f"[{color}{'#' * filled}{RESET}{PALETTE['muted']}{'-' * empty}{RESET}]"


def _window_title(window: dict[str, Any], fallback: str) -> str:
    minutes = _coerce_number(window.get("window_minutes"))
    if minutes is None:
        return fallback
    value = int(minutes)
    if value == 300:
        return "5h left"
    if value == 10080:
        return "7d left"
    if value % 1440 == 0:
        return f"{value // 1440}d left"
    if value % 60 == 0:
        return f"{value // 60}h left"
    return f"{value}m left"


def _uncached_codex_percent(metrics: dict[str, Any]) -> float | None:
    input_tokens = _coerce_number(metrics.get("last_input_tokens"))
    cached = _coerce_number(metrics.get("last_cached_input_tokens"))
    if input_tokens in (None, 0):
        return None
    cached_value = cached or 0.0
    uncached = max(0.0, input_tokens - cached_value)
    return (uncached / input_tokens) * 100.0


def _fresh_claude_percent(last_request: dict[str, Any]) -> float | None:
    input_tokens = _coerce_number(last_request.get("input_tokens")) or 0.0
    cache_creation = _coerce_number(last_request.get("cache_creation_input_tokens")) or 0.0
    cache_read = _coerce_number(last_request.get("cache_read_input_tokens")) or 0.0
    prompt_total = input_tokens + cache_creation + cache_read
    if prompt_total <= 0:
        return None
    return ((input_tokens + cache_creation) / prompt_total) * 100.0


def _claude_status(warnings: list[str]) -> str | None:
    if not warnings:
        return None
    for warning in warnings:
        if "resets" in warning or "limit" in warning.lower():
            return warning
    return warnings[0]


def _warning_line(text: str) -> str:
    return f"{PALETTE['warn']}Warn{RESET}      {text}"


def _label_line(label: str, value: str) -> str:
    return f"{PALETTE['info']}{label:<10}{RESET}  {value}"


def _compact_number(value: float) -> str:
    absolute = abs(value)
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if absolute >= 1_000:
        return f"{value / 1_000:.1f}k"
    return str(int(value))


def _pretty_text(value: str) -> str:
    return value.replace("_", "-")


def _coerce_number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_epoch(value: Any) -> str | None:
    numeric = _coerce_number(value)
    if numeric is None:
        return None
    if numeric > 10**12:
        numeric /= 1000.0
    instant = datetime.fromtimestamp(numeric).astimezone()
    now = datetime.now().astimezone()
    if instant.date() == now.date():
        return instant.strftime("%H:%M")
    return instant.strftime("%b %d %H:%M")


def _format_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _snapshot_signature(snapshot: dict[str, Any]) -> str:
    stable = {key: value for key, value in snapshot.items() if key != "generated_at"}
    return json.dumps(stable, sort_keys=True, separators=(",", ":"))


def _enter_watch_terminal() -> str:
    return f"{ENTER_ALT_SCREEN}{HIDE_CURSOR}{CLEAR_SCREEN_HOME}"


def _exit_watch_terminal() -> str:
    return f"{SHOW_CURSOR}{EXIT_ALT_SCREEN}"


def _should_render_frame(*, interactive: bool, signature: str, last_signature: str | None) -> bool:
    if interactive:
        return True
    return signature != last_signature


def _advance_next_tick(previous_tick: float, now: float, interval: int) -> float:
    return max(previous_tick + interval, now)


def _is_interactive_stream(stream: Any) -> bool:
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except Exception:
        return False


def _terminal_width() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 100
