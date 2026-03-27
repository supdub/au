from __future__ import annotations

import unittest

from agent_usage_cli.render import (
    CLEAR_SCREEN_HOME,
    ENTER_ALT_SCREEN,
    EXIT_ALT_SCREEN,
    HIDE_CURSOR,
    SHOW_CURSOR,
    _advance_next_tick,
    _enter_watch_terminal,
    _exit_watch_terminal,
    _is_interactive_stream,
    _should_render_frame,
    _snapshot_signature,
)


class RenderTests(unittest.TestCase):
    def test_snapshot_signature_ignores_generated_at(self) -> None:
        first = {
            "generated_at": "2026-03-27T19:00:00Z",
            "tool_version": "0.1.0",
            "providers": [{"id": "codex", "auth": "logged_in"}],
        }
        second = {
            "generated_at": "2026-03-27T19:00:05Z",
            "tool_version": "0.1.0",
            "providers": [{"id": "codex", "auth": "logged_in"}],
        }
        self.assertEqual(_snapshot_signature(first), _snapshot_signature(second))

    def test_non_interactive_watch_only_renders_on_data_changes(self) -> None:
        self.assertFalse(
            _should_render_frame(
                interactive=False,
                signature="same",
                last_signature="same",
            )
        )
        self.assertTrue(
            _should_render_frame(
                interactive=False,
                signature="next",
                last_signature="same",
            )
        )

    def test_interactive_watch_renders_every_tick(self) -> None:
        self.assertTrue(
            _should_render_frame(
                interactive=True,
                signature="same",
                last_signature="same",
            )
        )

    def test_is_interactive_stream_handles_stream_without_isatty(self) -> None:
        class NoTty:
            pass

        self.assertFalse(_is_interactive_stream(NoTty()))

    def test_enter_watch_terminal_uses_alternate_screen_and_hides_cursor(self) -> None:
        self.assertEqual(
            _enter_watch_terminal(),
            f"{ENTER_ALT_SCREEN}{HIDE_CURSOR}{CLEAR_SCREEN_HOME}",
        )

    def test_exit_watch_terminal_restores_cursor_and_screen(self) -> None:
        self.assertEqual(
            _exit_watch_terminal(),
            f"{SHOW_CURSOR}{EXIT_ALT_SCREEN}",
        )

    def test_advance_next_tick_keeps_fixed_cadence_without_waiting_extra_after_slow_work(self) -> None:
        self.assertEqual(_advance_next_tick(10.0, 10.2, 1), 11.0)
        self.assertEqual(_advance_next_tick(10.0, 12.7, 1), 12.7)


if __name__ == "__main__":
    unittest.main()
