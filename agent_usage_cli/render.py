from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime
from typing import Any


RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
ENTER_ALT_SCREEN = "\033[?1049h"
EXIT_ALT_SCREEN = "\033[?1049l"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
CLEAR_SCREEN_HOME = "\033[2J\033[H"

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
WAVE_FRAMES = ("▁▂▃▄▅▆▇█", "▂▃▄▅▆▇█▆", "▃▄▅▆▇█▆▅", "▄▅▆▇█▆▅▄")

PALETTE = {
    "gold": "\033[38;5;220m",
    "sun": "\033[38;5;221m",
    "mint": "\033[38;5;121m",
    "cyan": "\033[38;5;117m",
    "sky": "\033[38;5;111m",
    "rose": "\033[38;5;210m",
    "violet": "\033[38;5;183m",
    "warn": "\033[38;5;215m",
    "bad": "\033[38;5;203m",
    "muted": "\033[38;5;245m",
    "panel": "\033[38;5;67m",
    "edge": "\033[38;5;31m",
    "text": "\033[38;5;255m",
}

PROVIDER_ACCENTS = {
    "codex": PALETTE["gold"],
    "claude": PALETTE["sky"],
    "cursor": PALETTE["mint"],
}


def build_watch_frame(snapshot: dict[str, Any], interval: int, width: int | None = None) -> str:
    frame_width = max(72, width or _terminal_width())
    providers = snapshot["providers"]
    logged_in_count = sum(1 for provider in providers if provider.get("auth") == "logged_in")
    lines: list[str] = []

    lines.extend(_render_header(snapshot, interval, frame_width, logged_in_count, providers))
    lines.append("")

    for index, provider in enumerate(providers):
        lines.extend(_render_provider(provider, frame_width))
        if index != len(providers) - 1:
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_watch(snapshot: dict[str, Any], interval: int) -> None:
    sys.stdout.write(CLEAR_SCREEN_HOME)
    sys.stdout.write(build_watch_frame(snapshot, interval))
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


def _render_header(
    snapshot: dict[str, Any],
    interval: int,
    width: int,
    logged_in_count: int,
    providers: list[dict[str, Any]],
) -> list[str]:
    spinner = _spinner(snapshot["generated_at"])
    wave = _wave(snapshot["generated_at"])
    updated_at = _format_timestamp(snapshot["generated_at"])
    toc = "  ".join(_toc_chip(index, provider) for index, provider in enumerate(providers, start=1))

    lines = [
        f"{PALETTE['gold']}{BOLD}{spinner} AU{RESET}  {PALETTE['sun']}{BOLD}gold watch{RESET}"
        f"  {PALETTE['muted']}refresh {interval}s{RESET}"
        f"  {PALETTE['mint']}{logged_in_count}/{len(providers)} ready{RESET}",
        f"{PALETTE['muted']}Updated {updated_at}{RESET}",
        f"{PALETTE['gold']}{wave}{RESET}",
    ]

    summary_lines = [
        _info_pair("Contents", toc),
        _info_pair("Version", str(snapshot.get("tool_version", "?"))),
        _info_pair("Modes", _mode_rollup(providers)),
    ]
    return lines + _box("Quick TOC", summary_lines, width, PALETTE["gold"])


def _render_provider(provider: dict[str, Any], width: int) -> list[str]:
    usage = provider.get("usage") or {}
    windows = usage.get("windows") or {}
    metrics = usage.get("metrics") or {}
    session = usage.get("session") or {}
    account = provider.get("account") or {}
    accent = PROVIDER_ACCENTS.get(provider["id"], PALETTE["cyan"])
    bar_width = max(12, min(28, width - 34))

    lines: list[str] = []
    if provider.get("auth") != "logged_in":
        for action in provider.get("actions") or []:
            lines.append(_info_pair("Login", action))
        for warning in provider.get("warnings") or []:
            lines.append(_info_pair("Warn", warning))
        if usage.get("summary"):
            lines.append(_info_pair("Status", usage["summary"]))
    elif provider["id"] == "codex":
        lines.extend(_render_codex(metrics, windows, session, bar_width))
    elif provider["id"] == "claude":
        lines.extend(_render_claude(provider, metrics, windows, session, account, bar_width))
    elif provider["id"] == "cursor":
        lines.extend(_render_cursor(provider, metrics, account))
    elif usage.get("summary"):
        lines.append(_info_pair("Status", usage["summary"]))

    return _box(_provider_title(provider), lines, width, accent)


def _provider_title(provider: dict[str, Any]) -> str:
    auth = provider.get("auth", "unknown")
    auth_color = PALETTE["warn"]
    if auth == "logged_in":
        auth_color = PALETTE["mint"]
    elif auth == "login_required":
        auth_color = PALETTE["bad"]

    bits = [
        f"{BOLD}{provider['label']}{RESET}",
        f"{auth_color}{auth}{RESET}",
    ]
    if provider.get("mode"):
        bits.append(f"{PALETTE['cyan']}mode={_pretty_text(str(provider['mode']))}{RESET}")
    if provider.get("billing"):
        bits.append(f"{PALETTE['sun']}billing={_pretty_text(str(provider['billing']))}{RESET}")
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
        lines.append(_info_pair("Plan", str(plan_type)))

    for name in ("primary", "secondary"):
        window = windows.get(name) or {}
        line = _quota_line(_window_title(window, name), window, bar_width)
        if line:
            lines.append(line)

    last_total = _coerce_number(metrics.get("last_total_tokens"))
    uncached = _uncached_codex_percent(metrics)
    if last_total is not None and uncached is not None:
        lines.append(
            _info_pair(
                "Turn",
                f"{_compact_number(last_total)} tokens  {PALETTE['muted']}uncached{RESET} {uncached:.1f}%",
            )
        )
    elif last_total is not None:
        lines.append(_info_pair("Turn", f"{_compact_number(last_total)} tokens"))

    context = _coerce_number(metrics.get("model_context_window"))
    if context is not None:
        lines.append(_info_pair("Context", f"{_compact_number(context)} tokens"))
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
        lines.append(_info_pair("Plan", str(subscription)))

    showed_window = False
    for name in ("primary", "secondary"):
        window = windows.get(name) or {}
        line = _quota_or_status_line(_window_title(window, name), window, bar_width)
        if line:
            lines.append(line)
            showed_window = True

    last_request = (session.get("last_request") or {}) if isinstance(session.get("last_request"), dict) else {}
    last_total = _coerce_number(last_request.get("total_tokens"))
    fresh = _fresh_claude_percent(last_request)
    if last_total is not None and fresh is not None:
        lines.append(
            _info_pair(
                "Last req",
                f"{_compact_number(last_total)} tokens  {PALETTE['muted']}fresh in{RESET} {fresh:.1f}%",
            )
        )
    elif last_total is not None:
        lines.append(_info_pair("Last req", f"{_compact_number(last_total)} tokens"))

    requests = _coerce_number(metrics.get("requests"))
    total_tokens = _coerce_number(metrics.get("total_tokens"))
    if requests is not None and total_tokens is not None:
        lines.append(_info_pair("Session", f"{int(requests)} req  /  {_compact_number(total_tokens)} tokens"))

    if not showed_window:
        status = _claude_status(provider.get("warnings") or [])
        if status:
            lines.append(_info_pair("Status", status))
    return lines


def _render_cursor(provider: dict[str, Any], metrics: dict[str, Any], account: dict[str, Any]) -> list[str]:
    lines: list[str] = []

    plan_bits = []
    if account.get("subscription_type"):
        plan_bits.append(str(account["subscription_type"]))
    if provider.get("billing"):
        plan_bits.append(_pretty_text(str(provider["billing"])))
    if plan_bits:
        lines.append(_info_pair("Plan", " ".join(plan_bits)))

    included = metrics.get("included_usage_dollars")
    credit = metrics.get("credit_dollars")
    if included not in (None, "", 0) or credit not in (None, "", 0):
        parts: list[str] = []
        if included not in (None, "", 0):
            parts.append(f"included ${included}")
        if credit not in (None, "", 0):
            parts.append(f"credit ${credit}")
        lines.append(_info_pair("Wallet", "  /  ".join(parts)))

    model = account.get("current_model")
    if model:
        lines.append(_info_pair("Model", str(model)))

    lines.append(_info_pair("Live usage", "unavailable from installed CLI"))
    return lines


def _quota_or_status_line(label: str, window: dict[str, Any], bar_width: int) -> str | None:
    quota = _quota_line(label, window, bar_width)
    if quota:
        return quota

    status = _pretty_text(str(window.get("status"))) if window.get("status") else None
    reset_text = _format_epoch(window.get("resets_at"))
    if not status and not reset_text:
        return None

    parts: list[str] = []
    if status:
        parts.append(status)
    if reset_text:
        parts.append(f"reset {reset_text}")
    return _info_pair(label, "  /  ".join(parts))


def _quota_line(label: str, window: dict[str, Any], bar_width: int) -> str | None:
    used = _coerce_number(window.get("used_percent"))
    if used is None:
        return None
    remaining = max(0.0, min(100.0, 100.0 - used))
    reset_text = _format_epoch(window.get("resets_at"))
    text = f"{_joy_meter(remaining, bar_width)}  {remaining:5.1f}% left"
    if reset_text:
        text += f"  {PALETTE['muted']}reset{RESET} {reset_text}"
    return _info_pair(label, text)


def _joy_meter(remaining: float, width: int) -> str:
    width = max(10, width)
    filled = int(round((remaining / 100.0) * width))
    empty = max(0, width - filled)
    color = PALETTE["mint"] if remaining >= 60 else PALETTE["sun"] if remaining >= 30 else PALETTE["rose"]
    edge = PALETTE["cyan"] if filled else color
    body = "█" * max(0, filled - 1)
    tip = "▓" if filled else ""
    tail = "·" * empty
    return f"{color}[{body}{edge}{tip}{RESET}{PALETTE['muted']}{tail}{RESET}{color}]{RESET}"


def _box(title: str, body_lines: list[str], width: int, accent: str) -> list[str]:
    inner_width = max(40, min(width - 4, 110))
    title_plain = _visible_text(title)
    top_fill = max(2, inner_width - len(title_plain) - 2)
    lines = [f"{accent}╭─{RESET} {title} {accent}{'─' * top_fill}╮{RESET}"]
    for line in body_lines or [""]:
        lines.append(f"{accent}│{RESET} {_fit_ansi(line, inner_width)} {accent}│{RESET}")
    lines.append(f"{accent}╰{'─' * (inner_width + 2)}╯{RESET}")
    return lines


def _toc_chip(index: int, provider: dict[str, Any]) -> str:
    accent = PROVIDER_ACCENTS.get(provider["id"], PALETTE["cyan"])
    auth = provider.get("auth", "unknown")
    auth_color = PALETTE["mint"] if auth == "logged_in" else PALETTE["warn"]
    auth_mark = "●" if auth == "logged_in" else "!"
    label = provider["label"].replace(" Code", "").replace(" Agent", "")
    mode = _pretty_text(str(provider.get("billing") or provider.get("mode", "unknown")))
    return (
        f"{accent}[{index}]{RESET} {label} "
        f"{auth_color}{auth_mark}{RESET} {PALETTE['muted']}{mode}{RESET}"
    )


def _mode_rollup(providers: list[dict[str, Any]]) -> str:
    parts = []
    for provider in providers:
        label = provider["label"].split()[0]
        mode = _pretty_text(str(provider.get("mode", "unknown")))
        parts.append(f"{label}:{mode}")
    return "  /  ".join(parts)


def _spinner(generated_at: str) -> str:
    try:
        parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        index = int(parsed.timestamp()) % len(SPINNER_FRAMES)
    except ValueError:
        index = 0
    return SPINNER_FRAMES[index]


def _wave(generated_at: str) -> str:
    try:
        parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        index = int(parsed.timestamp()) % len(WAVE_FRAMES)
    except ValueError:
        index = 0
    return WAVE_FRAMES[index]


def _info_pair(label: str, value: str) -> str:
    return f"{PALETTE['cyan']}{label:<10}{RESET} {PALETTE['text']}{value}{RESET}"


def _visible_text(text: str) -> str:
    return ANSI_RE.sub("", text)


def _fit_ansi(text: str, width: int) -> str:
    visible = _visible_text(text)
    if len(visible) > width:
        clipped = visible[: max(0, width - 1)] + ("…" if width > 0 else "")
        return clipped.ljust(width)
    return text + (" " * (width - len(visible)))


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
