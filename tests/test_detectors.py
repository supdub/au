from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from agent_usage_cli.detectors import (
    RuntimeContext,
    detect_claude,
    detect_codex,
    detect_cursor,
)


class DetectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.home = Path(self.tmpdir.name)
        self.now = datetime(2026, 3, 27, tzinfo=timezone.utc)
        self.base_env = dict(os.environ)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def ctx(self, **env: str) -> RuntimeContext:
        merged = dict(self.base_env)
        merged["AU_DISABLE_SUBPROCESS"] = "1"
        merged.update(env)
        return RuntimeContext(home=self.home, env=merged, now=self.now)

    def test_codex_logged_in_plan_mode(self) -> None:
        codex_dir = self.home / ".codex"
        codex_dir.mkdir()
        (codex_dir / "auth.json").write_text(
            json.dumps(
                {
                    "auth_mode": "chatgpt",
                    "OPENAI_API_KEY": None,
                    "tokens": {
                        "access_token": "a",
                        "refresh_token": "r",
                        "account_id": "acct",
                    },
                }
            ),
            encoding="utf-8",
        )
        report = detect_codex(self.ctx())
        self.assertEqual(report.auth, "logged_in")
        self.assertEqual(report.mode, "plan")
        self.assertIn("No local Codex usage event found yet.", report.warnings)

    def test_codex_reads_latest_usage_event(self) -> None:
        codex_dir = self.home / ".codex"
        session_dir = codex_dir / "sessions" / "2026" / "03" / "27"
        session_dir.mkdir(parents=True)
        (codex_dir / "auth.json").write_text(
            json.dumps(
                {
                    "auth_mode": "chatgpt",
                    "OPENAI_API_KEY": None,
                    "tokens": {"access_token": "a", "refresh_token": "r"},
                }
            ),
            encoding="utf-8",
        )
        (session_dir / "rollout.jsonl").write_text(
            "\n".join(
                [
                    json.dumps({"type": "session_meta", "payload": {"id": "s1"}}),
                    json.dumps(
                        {
                            "type": "event_msg",
                            "payload": {
                                "type": "token_count",
                                "info": {
                                    "total_token_usage": {
                                        "input_tokens": 100,
                                        "cached_input_tokens": 50,
                                        "output_tokens": 20,
                                        "reasoning_output_tokens": 5,
                                        "total_tokens": 120,
                                    },
                                    "last_token_usage": {
                                        "input_tokens": 10,
                                        "cached_input_tokens": 5,
                                        "output_tokens": 2,
                                        "reasoning_output_tokens": 1,
                                        "total_tokens": 12,
                                    },
                                    "model_context_window": 258400,
                                },
                                "rate_limits": {
                                    "plan_type": "pro",
                                    "primary": {"used_percent": 6.0, "window_minutes": 300, "resets_at": 1},
                                },
                            },
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        report = detect_codex(self.ctx())
        self.assertEqual(report.usage.metrics["total_tokens"], 120)
        self.assertEqual(report.usage.windows["primary"]["used_percent"], 6.0)

    def test_claude_api_key_overrides_mode(self) -> None:
        claude_dir = self.home / ".claude"
        claude_dir.mkdir()
        (claude_dir / ".credentials.json").write_text(
            json.dumps(
                {
                    "claudeAiOauth": {
                        "accessToken": "token",
                        "expiresAt": 1774657345238,
                        "subscriptionType": "pro",
                        "rateLimitTier": "default_claude_ai",
                    }
                }
            ),
            encoding="utf-8",
        )
        report = detect_claude(self.ctx(ANTHROPIC_API_KEY="x"))
        self.assertEqual(report.mode, "api")
        self.assertTrue(report.warnings)

    def test_claude_aggregates_latest_session_by_request(self) -> None:
        claude_dir = self.home / ".claude"
        projects_dir = claude_dir / "projects" / "-tmp-project"
        projects_dir.mkdir(parents=True)
        (claude_dir / ".credentials.json").write_text(
            json.dumps(
                {
                    "claudeAiOauth": {
                        "accessToken": "token",
                        "expiresAt": 1774657345238,
                        "subscriptionType": "pro",
                    }
                }
            ),
            encoding="utf-8",
        )
        session_file = projects_dir / "session.jsonl"
        session_file.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "type": "assistant",
                            "requestId": "req-1",
                            "timestamp": "2026-03-27T17:00:00Z",
                            "message": {
                                "usage": {
                                    "input_tokens": 3,
                                    "cache_creation_input_tokens": 0,
                                    "cache_read_input_tokens": 10,
                                    "output_tokens": 8,
                                }
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "type": "assistant",
                            "requestId": "req-1",
                            "timestamp": "2026-03-27T17:00:01Z",
                            "message": {
                                "usage": {
                                    "input_tokens": 3,
                                    "cache_creation_input_tokens": 0,
                                    "cache_read_input_tokens": 10,
                                    "output_tokens": 20,
                                    "server_tool_use": {"web_search_requests": 1, "web_fetch_requests": 0},
                                }
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "type": "assistant",
                            "requestId": "req-2",
                            "timestamp": "2026-03-27T17:01:00Z",
                            "message": {
                                "usage": {
                                    "input_tokens": 5,
                                    "cache_creation_input_tokens": 4,
                                    "cache_read_input_tokens": 0,
                                    "output_tokens": 6,
                                }
                            },
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        report = detect_claude(self.ctx())
        self.assertEqual(report.usage.metrics["requests"], 2)
        self.assertEqual(report.usage.metrics["total_tokens"], 48)
        self.assertEqual(report.usage.metrics["web_search_requests"], 1)

    def test_claude_reads_rate_limit_windows_from_insights_stream(self) -> None:
        claude_dir = self.home / ".claude"
        claude_dir.mkdir()
        (claude_dir / ".credentials.json").write_text(
            json.dumps(
                {
                    "claudeAiOauth": {
                        "accessToken": "token",
                        "expiresAt": 1774657345238,
                        "subscriptionType": "pro",
                    }
                }
            ),
            encoding="utf-8",
        )
        ctx = RuntimeContext(
            home=self.home,
            env={**self.base_env, "AU_ENABLE_CLAUDE_INSIGHTS": "1"},
            now=self.now,
        )
        with patch(
            "agent_usage_cli.detectors.run_json_command",
            return_value={"loggedIn": True, "subscriptionType": "pro"},
        ), patch(
            "agent_usage_cli.detectors.run_json_stream_command",
            return_value=[
                {
                    "type": "rate_limit_event",
                    "rate_limit_info": {
                        "status": "allowed",
                        "rateLimitType": "five_hour",
                        "resetsAt": 1774656000,
                    },
                }
            ],
        ):
            report = detect_claude(ctx)
        self.assertEqual(report.usage.windows["primary"]["window_minutes"], 300)
        self.assertEqual(report.usage.windows["primary"]["status"], "allowed")
        self.assertEqual(report.usage.windows["primary"]["resets_at"], 1774656000)

    def test_cursor_usage_based_from_agent_files(self) -> None:
        auth_dir = self.home / ".config" / "cursor"
        auth_dir.mkdir(parents=True)
        (auth_dir / "auth.json").write_text(
            json.dumps(
                {
                    "accessToken": "token",
                    "refreshToken": "refresh",
                }
            ),
            encoding="utf-8",
        )
        cursor_dir = self.home / ".cursor"
        cursor_dir.mkdir()
        (cursor_dir / "cli-config.json").write_text(
            json.dumps(
                {
                    "authInfo": {
                        "email": "person@example.com",
                        "displayName": "Person",
                    },
                    "model": {"displayName": "Opus 4.6 1M Thinking"},
                    "maxMode": False,
                }
            ),
            encoding="utf-8",
        )
        (cursor_dir / "statsig-cache.json").write_text(
            json.dumps(
                {
                    "data": json.dumps(
                        {
                            "user": {
                                "custom": {
                                    "shouldUseNewPricing": True,
                                    "stripeMembershipStatus": "pro",
                                    "stripeSubscriptionStatus": "active",
                                    "privacyModeType": "NO_STORAGE",
                                }
                            },
                            "dynamic_configs": {
                                "usage": {
                                    "value": {
                                        "autoTitle": "Auto + Composer",
                                        "autoUsageBarLabel": "your included total usage",
                                        "apiTitle": "API",
                                        "apiUsageBarLabel": "your included API usage",
                                        "included_usage_dollars": 40,
                                        "credit_dollars": 25,
                                        "usage_limit_policy_id": 140,
                                    }
                                }
                            },
                        }
                    )
                }
            ),
            encoding="utf-8",
        )
        report = detect_cursor(self.ctx())
        self.assertEqual(report.auth, "logged_in")
        self.assertEqual(report.mode, "plan")
        self.assertEqual(report.billing, "usage_based")
        self.assertEqual(report.usage.metrics["included_usage_dollars"], 40)
        self.assertIn("included total usage", report.usage.meaning)

    def test_cursor_missing_login_requests_cursor_agent_login(self) -> None:
        report = detect_cursor(self.ctx())
        self.assertEqual(report.auth, "login_required")
        self.assertIn("Run `cursor-agent login`.", report.actions)


if __name__ == "__main__":
    unittest.main()
