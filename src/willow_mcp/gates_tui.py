"""willow_mcp/gates_tui.py — the interactive terminal front-end for
`willow-mcp gates`.

`gates_panel.render_tui()` prints a one-shot snapshot; this is the thing you
actually sit in and use: arrow keys / j-k move a highlighted row, enter or
space fires whatever `gates_actions.describe()` says that row does, and the
screen re-collects live state after every action. All mutation logic lives
in `gates_actions.py` — this module is deliberately thin curses glue over
it, so the "what does pressing this row do" question has one tested answer
shared with the live HTML dashboard (`gates_serve.py`).

Falls back to the static `render_tui()` snapshot automatically when stdout
isn't a real terminal (piped, redirected, CI) — curses has nothing to draw
to in that case, and the existing `--json`/static output already serves
scripting.
"""
from __future__ import annotations

import curses
from typing import Optional

from . import gates_actions, gates_panel

_HELP = "↑/↓ or j/k move   enter/space act   r refresh   q quit"


def _button_pair(state: str) -> int:
    if state == "on":
        return 1
    if state == "warn":
        return 3
    return 2  # off


def _init_colors() -> None:
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_GREEN)   # on
    curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_RED)     # off
    curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_YELLOW)  # warn
    curses.init_pair(4, curses.COLOR_CYAN, -1)                    # header/help


def _timer_text(row) -> str:
    # Shares gates_panel's own formatting so the TUI and the static
    # snapshot never describe the same state two different ways.
    return gates_panel._timer_text(row)


def _draw(stdscr, rows: list, selected: int, status: str, scroll: int) -> int:
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    stdscr.addstr(0, 0, "willow-mcp gates — interactive".ljust(w - 1)[: w - 1],
                  curses.color_pair(4) | curses.A_BOLD)
    stdscr.addstr(1, 0, _HELP[: w - 1], curses.color_pair(4))

    body_h = h - 4
    if selected < scroll:
        scroll = selected
    elif selected >= scroll + body_h:
        scroll = selected - body_h + 1

    for i in range(body_h):
        idx = scroll + i
        if idx >= len(rows):
            break
        row = rows[idx]
        y = 2 + i
        is_selected = idx == selected
        button = f"[{row.state.upper():^4}]"
        rest = f" {row.scope:<16} {row.friendly:<30} {_timer_text(row):<26} {row.label} — {row.detail}"
        line = (button + rest)[: w - 1].ljust(w - 1)

        # Whole line first (plain, or reverse-video if this is the focused
        # row) — then the button prefix is redrawn on top with its real
        # on/off/warn color, so every row's button stays colored and the
        # focused row is still distinguishable by the reverse band around it.
        stdscr.addstr(y, 0, line, curses.A_REVERSE if is_selected else 0)
        button_attr = curses.color_pair(_button_pair(row.state)) | curses.A_BOLD
        if is_selected:
            button_attr |= curses.A_REVERSE
        stdscr.addstr(y, 0, button[: w - 1], button_attr)

    stdscr.addstr(h - 1, 0, status[: w - 1].ljust(w - 1), curses.A_BOLD)
    stdscr.refresh()
    return scroll


def _prompt(stdscr, label: str) -> str:
    h, w = stdscr.getmaxyx()
    stdscr.move(h - 1, 0)
    stdscr.clrtoeol()
    stdscr.addstr(h - 1, 0, label[: w - 1])
    stdscr.refresh()
    curses.echo()
    curses.curs_set(1)
    try:
        raw = stdscr.getstr(h - 1, min(len(label), w - 1))
    finally:
        curses.noecho()
        curses.curs_set(0)
    try:
        return raw.decode("utf-8")
    except Exception:
        return ""


def _collect_inputs(stdscr, needs: tuple) -> dict:
    inputs = {}
    for field in needs:
        inputs[field] = _prompt(stdscr, f"{field}: ")
    return inputs


def _handle_action(stdscr, row) -> str:
    spec = gates_actions.describe(row)
    if spec.kind == "none":
        return spec.reason
    if spec.needs:
        inputs = _collect_inputs(stdscr, spec.needs)
    else:
        inputs = {}
    result = gates_actions.apply(row, inputs)
    return result["message"]


def _loop(stdscr, app_id: str) -> None:
    curses.curs_set(0)
    _init_colors()
    stdscr.keypad(True)
    selected, scroll = 0, 0
    status = _HELP
    rows = gates_panel.collect(app_id)

    while True:
        selected = max(0, min(selected, max(len(rows) - 1, 0)))
        scroll = _draw(stdscr, rows, selected, status, scroll)
        key = stdscr.getch()

        if key in (ord("q"), 27):
            return
        elif key in (curses.KEY_UP, ord("k")):
            selected = max(0, selected - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            selected = min(len(rows) - 1, selected + 1)
        elif key == ord("r"):
            rows = gates_panel.collect(app_id)
            status = "refreshed"
        elif key in (curses.KEY_ENTER, 10, 13, ord(" ")) and rows:
            status = _handle_action(stdscr, rows[selected])
            rows = gates_panel.collect(app_id)


def run(app_id: str = "") -> None:
    """Launch the interactive TUI. Blocks until the user quits ('q'/Esc)."""
    curses.wrapper(_loop, app_id)
