"""Tests for gates_tui.py's non-curses helpers.

The curses input loop itself (`_loop`, `run`) needs a real terminal and was
verified manually via a pty harness (navigate, toggle a permission, grant a
lease through the text prompts) rather than in this suite — curses tests
against a fake screen are notoriously environment-dependent (TERM, screen
size, color support) and not worth the flakiness here. What IS worth
pinning in CI is the small amount of real logic that doesn't need a
terminal: the color-mapping and the timer-text passthrough to gates_panel.
"""
from willow_mcp import gates_tui, gates_panel


def test_button_pair_maps_every_known_state():
    assert gates_tui._button_pair("on") == 1
    assert gates_tui._button_pair("off") == 2
    assert gates_tui._button_pair("warn") == 3


def test_button_pair_defaults_off_color_for_unknown_state():
    assert gates_tui._button_pair("something_new") == 2


def test_timer_text_delegates_to_gates_panel(monkeypatch):
    """gates_tui must describe timers the same way the static snapshot
    does — two different-looking implementations here would drift."""
    row = gates_panel.GateRow(id="x", label="x", scope="global", state="off",
                               detail="", timer_shape="standing")
    assert gates_tui._timer_text(row) == gates_panel._timer_text(row)
