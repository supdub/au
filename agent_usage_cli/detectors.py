from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from agent_usage_cli.models import ProviderReport, UsageSummary
from agent_usage_cli.utils import (
    env_flag,
    iter_jsonl,
    latest_matching_file,
    read_json,
    read_toml,
    run_json_command,
    run_json_stream_command,
    run_text_command,
)


PROVIDER_ORDER = ("codex", "claude", "cursor")


@dataclass
class RuntimeContext:
    home: Path
    env: dict[str, str]
    now: datetime


def default_context() -> RuntimeContext:
    return RuntimeContext(home=Path.home(), env=dict(os.environ), now=datetime.now(timezone.utc))


def collect_reports(provider_ids: Iterable[str], ctx: RuntimeContext | None = None) -> list[ProviderReport]:
    active = ctx or default_context()
    reports: list[ProviderReport] = []
    for provider_id in provider_ids:
        if provider_id == "codex":
            reports.append(detect_codex(active))
        elif provider_id == "claude":
            reports.append(detect_claude(active))
        elif provider_id == "cursor":
            reports.append(detect_cursor(active))
        else:
            raise ValueError(f"unsupported provider: {provider_id}")
    return reports


def detect_codex(ctx: RuntimeContext) -> ProviderReport:
    auth_path = ctx.home / ".codex" / "auth.json"
    config_path = ctx.home / ".codex" / "config.toml"
    auth = read_json(auth_path) or {}
    config = read_toml(config_path) or {}
    codex_usage = _latest_codex_usage(ctx.home)

    auth_mode = auth.get("auth_mode")
    tokens = auth.get("tokens") or {}
    token_login = bool(tokens.get("access_token") and tokens.get("refresh_token"))
    chatgpt_login = auth_mode == "chatgpt" and token_login

    stored_api_key = bool(auth.get("OPENAI_API_KEY"))
    env_api_key = env_flag("OPENAI_API_KEY", ctx.env)
    api_key_configured = stored_api_key or env_api_key

    warnings: list[str] = []
    actions: list[str] = []
    if api_key_configured:
        warnings.append("OPENAI_API_KEY is configured; API-key usage may not match ChatGPT plan usage.")
    if not chatgpt_login:
        actions.append("Run `codex login`.")
    if chatgpt_login and not codex_usage:
        warnings.append("No local Codex usage event found yet.")

    usage = _codex_usage_summary(chatgpt_login, codex_usage)

    report = ProviderReport(
        id="codex",
        label="Codex",
        auth="logged_in" if chatgpt_login else "login_required",
        mode="plan" if chatgpt_login else "unknown",
        desired_mode="plan",
        usage=usage,
        warnings=warnings,
        actions=actions,
        evidence={
            "auth_file": str(auth_path),
            "config_file": str(config_path),
            "auth_mode": auth_mode,
            "token_login": token_login,
            "api_key_configured": api_key_configured,
            "env_openai_api_key": env_api_key,
            "stored_openai_api_key": stored_api_key,
            "trusted_project_count": len(config.get("projects", {})),
            "usage_session_file": codex_usage.get("session_path") if codex_usage else None,
        },
    )
    return report


def detect_claude(ctx: RuntimeContext) -> ProviderReport:
    credentials_path = ctx.home / ".claude" / ".credentials.json"
    settings_path = ctx.home / ".claude" / "settings.json"
    credentials = read_json(credentials_path) or {}
    oauth = credentials.get("claudeAiOauth") or {}
    auth_status = None
    rate_limit_windows: dict[str, Any] = {}
    if not env_flag("AU_DISABLE_SUBPROCESS", ctx.env):
        auth_status = run_json_command(["claude", "auth", "status"])
        if env_flag("AU_ENABLE_CLAUDE_INSIGHTS", ctx.env):
            rate_limit_windows = _claude_rate_limit_windows(ctx.env)
    if auth_status:
        oauth = {
            **oauth,
            "subscriptionType": auth_status.get("subscriptionType") or oauth.get("subscriptionType"),
        }
    claude_usage = _latest_claude_usage(ctx.home)

    expires_at = _coerce_int(oauth.get("expiresAt"))
    access_token = oauth.get("accessToken")
    token_present = bool(access_token)
    token_fresh = expires_at is None or expires_at > int(ctx.now.timestamp() * 1000)
    cli_logged_in = bool(auth_status and auth_status.get("loggedIn") is True)
    logged_in = cli_logged_in or (token_present and token_fresh)

    api_mode = env_flag("ANTHROPIC_API_KEY", ctx.env)
    warnings: list[str] = []
    actions: list[str] = []
    if api_mode:
        warnings.append("ANTHROPIC_API_KEY is set; API mode overrides plan-style usage expectations.")
    if token_present and not token_fresh:
        warnings.append("Stored Claude login looks expired.")
    if not logged_in:
        actions.append("Run `claude auth login`.")
    if logged_in and not claude_usage:
        warnings.append("No local Claude session usage was found yet.")
    if claude_usage and claude_usage.get("rate_limit_message"):
        warnings.append(claude_usage["rate_limit_message"])

    mode = "api" if api_mode else ("plan" if logged_in else "unknown")
    usage = _claude_usage_summary(logged_in, api_mode, claude_usage, rate_limit_windows)

    report = ProviderReport(
        id="claude",
        label="Claude Code",
        auth="logged_in" if logged_in else "login_required",
        mode=mode,
        desired_mode="api" if api_mode else "plan",
        usage=usage,
        warnings=warnings,
        actions=actions,
        evidence={
            "credentials_file": str(credentials_path),
            "settings_file": str(settings_path),
            "token_present": token_present,
            "token_fresh": token_fresh,
            "env_anthropic_api_key": api_mode,
            "auth_status_command": bool(auth_status),
            "rate_limit_windows_command": bool(rate_limit_windows),
            "usage_session_file": claude_usage.get("session_path") if claude_usage else None,
        },
        account={
            "subscription_type": oauth.get("subscriptionType"),
            "rate_limit_tier": oauth.get("rateLimitTier"),
            "expires_at_ms": expires_at,
            "email": auth_status.get("email") if auth_status else None,
            "org_name": auth_status.get("orgName") if auth_status else None,
        },
    )
    return report


def detect_cursor(ctx: RuntimeContext) -> ProviderReport:
    auth_path = ctx.home / ".config" / "cursor" / "auth.json"
    config_path = ctx.home / ".cursor" / "cli-config.json"
    statsig_path = ctx.home / ".cursor" / "statsig-cache.json"
    auth = read_json(auth_path) or {}
    config = read_json(config_path) or {}
    statsig = _load_cursor_statsig(statsig_path)

    status_text = None
    about_text = None
    if not env_flag("AU_DISABLE_SUBPROCESS", ctx.env):
        status_text = run_text_command(["cursor-agent", "status"])
        about_text = run_text_command(["cursor-agent", "about"])

    auth_info = config.get("authInfo") or {}
    model = config.get("model") or {}
    about_info = _parse_cursor_about(about_text)
    statsig_user = statsig.get("user") or {}
    statsig_custom = statsig_user.get("custom") or {}

    token_login = bool(auth.get("accessToken") and auth.get("refreshToken"))
    logged_in = bool(
        token_login
        or auth_info.get("email")
        or _cursor_status_email(status_text)
        or about_info.get("User Email")
    )
    api_mode = env_flag("CURSOR_API_KEY", ctx.env)
    billing = _cursor_billing_mode(statsig_custom)
    usage_labels = _cursor_usage_labels(statsig)
    usage_markers = _cursor_usage_markers(statsig)

    warnings: list[str] = []
    actions: list[str] = []
    if not logged_in:
        actions.append("Run `cursor-agent login`.")
    if api_mode:
        warnings.append("CURSOR_API_KEY is set; API-key usage can bypass plan-style Cursor Agent usage.")
    if logged_in and billing == "unknown":
        warnings.append("Cursor Agent pricing mode could not be verified from local agent data.")
    if logged_in and not api_mode:
        warnings.append("Cursor Agent does not expose current account usage totals through its installed CLI/config.")

    usage = _cursor_usage_summary(
        logged_in=logged_in,
        api_mode=api_mode,
        billing=billing,
        usage_labels=usage_labels,
        usage_markers=usage_markers,
    )

    report = ProviderReport(
        id="cursor",
        label="Cursor Agent",
        auth="logged_in" if logged_in else "login_required",
        mode="api" if api_mode else ("plan" if logged_in else "unknown"),
        billing=billing if logged_in else None,
        usage=usage,
        warnings=warnings,
        actions=actions,
        evidence={
            "auth_file": str(auth_path),
            "config_file": str(config_path),
            "statsig_file": str(statsig_path),
            "token_login": token_login,
            "status_text_present": bool(status_text),
            "about_text_present": bool(about_text),
            "should_use_new_pricing": statsig_custom.get("shouldUseNewPricing"),
            "usage_markers": usage_markers,
        },
        account={
            "email": auth_info.get("email") or about_info.get("User Email"),
            "display_name": auth_info.get("displayName"),
            "user_id": auth_info.get("userId"),
            "auth_id": auth_info.get("authId"),
            "current_model": model.get("displayName") or about_info.get("Model"),
            "cli_version": about_info.get("CLI Version"),
            "subscription_type": statsig_custom.get("stripeMembershipStatus"),
            "subscription_status": statsig_custom.get("stripeSubscriptionStatus"),
            "pricing_style": "usage_based" if statsig_custom.get("shouldUseNewPricing") else None,
            "privacy_mode_type": statsig_custom.get("privacyModeType"),
            "enterprise_user": True if statsig_custom.get("isEnterpriseUser") else None,
            "enterprise_trial_user": True if statsig_custom.get("isEnterpriseTrialUser") else None,
            "max_mode": True if config.get("maxMode") else None,
        },
    )
    return report


def _load_cursor_statsig(path: Path) -> dict[str, Any]:
    raw = read_json(path) or {}
    payload = raw.get("data")
    if isinstance(payload, str):
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return payload if isinstance(payload, dict) else {}


def _cursor_status_email(text: str | None) -> str | None:
    if not text:
        return None
    marker = "Logged in as "
    if marker not in text:
        return None
    return _coerce_str(text.split(marker, 1)[1].splitlines()[0])


def _parse_cursor_about(text: str | None) -> dict[str, str]:
    if not text:
        return {}
    info: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or "  " not in stripped:
            continue
        key, value = stripped.split("  ", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            info[key] = value
    return info


def _cursor_billing_mode(custom: dict[str, Any]) -> str:
    if custom.get("isEnterpriseUser") or custom.get("isEnterpriseTrialUser"):
        return "team"
    if custom.get("shouldUseNewPricing") is True:
        return "usage_based"
    if custom.get("stripeMembershipStatus") or custom.get("stripeSubscriptionStatus"):
        return "individual_plan"
    return "unknown"


def _cursor_usage_labels(statsig: dict[str, Any]) -> dict[str, str]:
    return {
        "auto_title": _coerce_str(_deep_find_first(statsig, {"autoTitle"})) or "Auto + Composer",
        "auto_label": _coerce_str(_deep_find_first(statsig, {"autoUsageBarLabel"})) or "your included total usage",
        "api_title": _coerce_str(_deep_find_first(statsig, {"apiTitle"})) or "API",
        "api_label": _coerce_str(_deep_find_first(statsig, {"apiUsageBarLabel"})) or "your included API usage",
        "auto_description": _coerce_str(_deep_find_first(statsig, {"autoDescription"})),
        "api_description": _coerce_str(_deep_find_first(statsig, {"apiDescription"})),
    }


def _cursor_usage_markers(statsig: dict[str, Any]) -> dict[str, Any]:
    markers: dict[str, Any] = {}
    for key in ("included_usage_dollars", "credit_dollars", "usage_limit_policy_id"):
        value = _deep_find_first(statsig, {key})
        if value not in (None, "", 0):
            markers[key] = value
    return markers


def _cursor_usage_summary(
    *,
    logged_in: bool,
    api_mode: bool,
    billing: str,
    usage_labels: dict[str, str],
    usage_markers: dict[str, Any],
) -> UsageSummary:
    if api_mode:
        return UsageSummary(
            kind="api",
            summary="CURSOR_API_KEY is active.",
            meaning="Requests can be billed and rate-limited as API usage because CURSOR_API_KEY is set.",
            source="environment",
            metrics=usage_markers,
        )

    if not logged_in:
        return UsageSummary(
            kind="plan",
            summary="No Cursor Agent login session detected.",
            meaning="Usage cannot be interpreted until `cursor-agent login` completes.",
        )

    if billing == "team":
        meaning = (
            "Usage belongs to the signed-in team workspace. The local agent can identify team-style billing, "
            "but it does not expose current spend or token totals."
        )
        summary = "Cursor Agent login detected under team billing."
    elif billing == "usage_based":
        meaning = (
            f"Usage on this account means {usage_labels['auto_label']} for {usage_labels['auto_title']}, "
            f"and {usage_labels['api_label']} for {usage_labels['api_title']} requests."
        )
        summary = "Cursor Agent login detected with usage-based pricing."
    elif billing == "individual_plan":
        meaning = "Usage refers to the signed-in personal Cursor account and its subscription entitlements."
        summary = "Cursor Agent login detected on a personal subscription."
    else:
        meaning = "Cursor Agent login exists, but local pricing mode could not be classified from available agent data."
        summary = "Cursor Agent login detected, but pricing mode is still unknown."

    if usage_labels.get("auto_description") and billing == "usage_based":
        meaning += f" {usage_labels['auto_title']}: {_cursor_sentence(usage_labels['auto_description'])}."
    if usage_labels.get("api_description") and billing == "usage_based":
        meaning += f" {usage_labels['api_title']}: {_cursor_sentence(usage_labels['api_description'])}."

    summary += " Current usage totals are not exposed by the installed Cursor Agent CLI."
    return UsageSummary(
        kind=billing if billing != "unknown" else "plan",
        summary=summary,
        meaning=meaning,
        source="cursor_agent_local",
        metrics=usage_markers,
    )


def _deep_find_first(value: Any, keys: set[str]) -> Any:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and item not in (None, "", [], {}):
                return item
        for item in value.values():
            found = _deep_find_first(item, keys)
            if found not in (None, "", [], {}):
                return found
    elif isinstance(value, list):
        for item in value:
            found = _deep_find_first(item, keys)
            if found not in (None, "", [], {}):
                return found
    return None


def _cursor_sentence(text: str) -> str:
    return text.rstrip(". ")


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _latest_codex_usage(home: Path) -> dict[str, Any] | None:
    session_root = home / ".codex" / "sessions"
    latest = latest_matching_file(session_root, "*.jsonl")
    if latest is None:
        return None

    latest_event: dict[str, Any] | None = None
    for item in iter_jsonl(latest):
        payload = item.get("payload") or {}
        if item.get("type") == "event_msg" and payload.get("type") == "token_count":
            latest_event = payload

    if latest_event is None:
        return None

    info = latest_event.get("info") or {}
    total = info.get("total_token_usage") or {}
    last = info.get("last_token_usage") or {}
    rate_limits = latest_event.get("rate_limits") or {}
    return {
        "session_path": str(latest),
        "session_mtime": _safe_mtime(latest),
        "metrics": {
            "input_tokens": total.get("input_tokens"),
            "cached_input_tokens": total.get("cached_input_tokens"),
            "output_tokens": total.get("output_tokens"),
            "reasoning_output_tokens": total.get("reasoning_output_tokens"),
            "total_tokens": total.get("total_tokens"),
            "last_input_tokens": last.get("input_tokens"),
            "last_cached_input_tokens": last.get("cached_input_tokens"),
            "last_output_tokens": last.get("output_tokens"),
            "last_reasoning_output_tokens": last.get("reasoning_output_tokens"),
            "last_total_tokens": last.get("total_tokens"),
            "model_context_window": info.get("model_context_window"),
        },
        "windows": {
            "primary": _normalize_rate_window(rate_limits.get("primary")),
            "secondary": _normalize_rate_window(rate_limits.get("secondary")),
        },
        "plan_type": rate_limits.get("plan_type"),
    }


def _codex_usage_summary(logged_in: bool, usage_data: dict[str, Any] | None) -> UsageSummary:
    if not logged_in:
        return UsageSummary(
            kind="plan",
            summary="No ChatGPT/Codex login session detected.",
            meaning="Usage cannot be interpreted until `codex login` completes.",
        )

    if not usage_data:
        return UsageSummary(
            kind="plan",
            summary="ChatGPT/Codex login session detected, but no local usage event was found yet.",
            meaning="Codex stores real token counts and window usage only after local sessions emit token-count events.",
        )

    metrics = usage_data["metrics"]
    windows = usage_data["windows"]
    return UsageSummary(
        kind="plan",
        summary=(
            f"Latest Codex session recorded {metrics.get('total_tokens')} total tokens; "
            f"last turn used {metrics.get('last_total_tokens')}."
        ),
        meaning="These values come from local Codex session token-count events and include plan window usage when available.",
        source="local_codex_session",
        metrics=metrics,
        windows=windows,
        session={
            "path": usage_data.get("session_path"),
            "updated_at_epoch": usage_data.get("session_mtime"),
            "plan_type": usage_data.get("plan_type"),
        },
    )


def _latest_claude_usage(home: Path) -> dict[str, Any] | None:
    project_root = home / ".claude" / "projects"
    latest = latest_matching_file(project_root, "*.jsonl")
    if latest is None:
        return None

    request_usage: dict[str, dict[str, Any]] = {}
    rate_limit_message = None
    last_timestamp = None
    sequence = 0

    for item in iter_jsonl(latest):
        if item.get("type") != "assistant":
            continue
        sequence += 1
        last_timestamp = item.get("timestamp") or last_timestamp
        if item.get("error") == "rate_limit":
            rate_limit_message = _extract_assistant_text(item) or "Claude hit a local rate limit in the latest session."
            continue

        request_id = item.get("requestId")
        usage = ((item.get("message") or {}).get("usage")) or {}
        if not request_id or not usage:
            continue

        normalized = {
            "input_tokens": _coerce_int(usage.get("input_tokens")) or 0,
            "cache_creation_input_tokens": _coerce_int(usage.get("cache_creation_input_tokens")) or 0,
            "cache_read_input_tokens": _coerce_int(usage.get("cache_read_input_tokens")) or 0,
            "output_tokens": _coerce_int(usage.get("output_tokens")) or 0,
            "web_search_requests": _coerce_int(((usage.get("server_tool_use") or {}).get("web_search_requests"))) or 0,
            "web_fetch_requests": _coerce_int(((usage.get("server_tool_use") or {}).get("web_fetch_requests"))) or 0,
        }
        normalized["total_tokens"] = (
            normalized["input_tokens"]
            + normalized["cache_creation_input_tokens"]
            + normalized["cache_read_input_tokens"]
            + normalized["output_tokens"]
        )
        normalized["timestamp"] = item.get("timestamp")
        normalized["sequence"] = sequence

        previous = request_usage.get(request_id)
        if previous is None or normalized["total_tokens"] >= previous["total_tokens"]:
            request_usage[request_id] = normalized

    if not request_usage and not rate_limit_message:
        return None

    totals = {
        "requests": len(request_usage),
        "input_tokens": sum(item["input_tokens"] for item in request_usage.values()),
        "cache_creation_input_tokens": sum(item["cache_creation_input_tokens"] for item in request_usage.values()),
        "cache_read_input_tokens": sum(item["cache_read_input_tokens"] for item in request_usage.values()),
        "output_tokens": sum(item["output_tokens"] for item in request_usage.values()),
        "web_search_requests": sum(item["web_search_requests"] for item in request_usage.values()),
        "web_fetch_requests": sum(item["web_fetch_requests"] for item in request_usage.values()),
    }
    totals["total_tokens"] = (
        totals["input_tokens"]
        + totals["cache_creation_input_tokens"]
        + totals["cache_read_input_tokens"]
        + totals["output_tokens"]
    )
    latest_request = None
    if request_usage:
        latest_request = max(
            request_usage.values(),
            key=lambda item: (
                _coerce_str(item.get("timestamp")) or "",
                _coerce_int(item.get("sequence")) or 0,
            ),
        )
    return {
        "session_path": str(latest),
        "session_mtime": _safe_mtime(latest),
        "session_timestamp": last_timestamp,
        "metrics": totals,
        "last_request": {
            "input_tokens": latest_request.get("input_tokens"),
            "cache_creation_input_tokens": latest_request.get("cache_creation_input_tokens"),
            "cache_read_input_tokens": latest_request.get("cache_read_input_tokens"),
            "output_tokens": latest_request.get("output_tokens"),
            "total_tokens": latest_request.get("total_tokens"),
            "timestamp": latest_request.get("timestamp"),
        }
        if latest_request
        else {},
        "rate_limit_message": rate_limit_message,
    }


def _claude_usage_summary(
    logged_in: bool,
    api_mode: bool,
    usage_data: dict[str, Any] | None,
    rate_limit_windows: dict[str, Any] | None = None,
) -> UsageSummary:
    windows = rate_limit_windows or {}
    if api_mode:
        return UsageSummary(
            kind="api",
            summary="ANTHROPIC_API_KEY is active.",
            meaning="Requests will be billed and rate-limited as API usage because ANTHROPIC_API_KEY is set.",
            source="environment",
            metrics=usage_data.get("metrics", {}) if usage_data else {},
            windows=windows,
            session={"path": usage_data.get("session_path")} if usage_data else {},
        )

    if not logged_in:
        return UsageSummary(
            kind="plan",
            summary="No Claude login session detected.",
            meaning="Usage cannot be interpreted until `claude auth login` completes.",
        )

    if not usage_data:
        return UsageSummary(
            kind="plan",
            summary="Claude login session detected, but no local session usage was found yet.",
            meaning="Claude stores token usage in session JSONL files after actual local sessions run.",
            windows=windows,
        )

    metrics = usage_data["metrics"]
    summary = (
        f"Latest Claude session recorded {metrics.get('requests')} requests and "
        f"{metrics.get('total_tokens')} total tokens."
    )
    if usage_data.get("rate_limit_message"):
        summary += " Latest session ended with a rate-limit notice."
    return UsageSummary(
        kind="plan",
        summary=summary,
        meaning="These values are aggregated from the latest local Claude session by taking the maximum usage snapshot per request.",
        source="local_claude_session",
        metrics=metrics,
        windows=windows,
        session={
            "path": usage_data.get("session_path"),
            "updated_at_epoch": usage_data.get("session_mtime"),
            "timestamp": usage_data.get("session_timestamp"),
            "last_request": usage_data.get("last_request") or {},
        },
    )


def _normalize_rate_window(window: Any) -> dict[str, Any]:
    data = window if isinstance(window, dict) else {}
    used_percent = data.get("used_percent")
    remaining_percent = data.get("remaining_percent")
    if used_percent is None and remaining_percent is not None:
        try:
            used_percent = 100.0 - float(remaining_percent)
        except (TypeError, ValueError):
            used_percent = None
    return {
        "used_percent": used_percent,
        "remaining_percent": remaining_percent,
        "window_minutes": data.get("window_minutes"),
        "resets_at": data.get("resets_at"),
        "status": data.get("status"),
        "overage_status": data.get("overage_status"),
        "overage_disabled_reason": data.get("overage_disabled_reason"),
        "is_using_overage": data.get("is_using_overage"),
    }


def _claude_rate_limit_windows(env: dict[str, str]) -> dict[str, Any]:
    if env_flag("ANTHROPIC_API_KEY", env):
        return {}
    command = ["claude", "-p", "/insights", "--output-format", "stream-json", "--verbose"]
    if shutil.which("stdbuf") is not None:
        command = ["stdbuf", "-oL", *command]
    events = run_json_stream_command(command, timeout=5.0, stop_types={"rate_limit_event"})
    windows: dict[str, Any] = {}
    for item in events:
        if item.get("type") != "rate_limit_event":
            continue
        info = item.get("rate_limit_info")
        normalized = _normalize_claude_rate_limit(info)
        if not normalized:
            continue
        windows[normalized["name"]] = normalized["window"]
    return windows


def _normalize_claude_rate_limit(info: Any) -> dict[str, Any] | None:
    data = info if isinstance(info, dict) else {}
    rate_limit_type = _coerce_str(data.get("rateLimitType")) or _coerce_str(data.get("rate_limit_type"))
    if not rate_limit_type:
        return None

    window_name = rate_limit_type
    window_minutes = None
    if rate_limit_type == "five_hour":
        window_name = "primary"
        window_minutes = 300
    elif rate_limit_type in {"seven_day", "weekly"}:
        window_name = "secondary"
        window_minutes = 10080

    used_percent = _coerce_int(data.get("usedPercent"))
    remaining_percent = _coerce_int(data.get("remainingPercent"))
    if used_percent is None and remaining_percent is not None:
        used_percent = 100 - remaining_percent

    return {
        "name": window_name,
        "window": _normalize_rate_window(
            {
                "used_percent": used_percent,
                "remaining_percent": remaining_percent,
                "window_minutes": window_minutes,
                "resets_at": data.get("resetsAt") or data.get("resets_at"),
                "status": data.get("status"),
                "overage_status": data.get("overageStatus") or data.get("overage_status"),
                "overage_disabled_reason": data.get("overageDisabledReason")
                or data.get("overage_disabled_reason"),
                "is_using_overage": data.get("isUsingOverage") if "isUsingOverage" in data else data.get("is_using_overage"),
            }
        ),
    }


def _safe_mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _extract_assistant_text(item: dict[str, Any]) -> str | None:
    message = item.get("message") or {}
    content = message.get("content") or []
    if isinstance(content, list):
        parts: list[str] = []
        for entry in content:
            if isinstance(entry, dict) and entry.get("type") == "text" and entry.get("text"):
                parts.append(str(entry["text"]))
        if parts:
            return " ".join(parts)
    return None
