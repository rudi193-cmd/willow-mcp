from willow_mcp.hook_parity import parity_report


def test_cursor_and_claude_hook_modules_align():
    report = parity_report()
    assert report["aligned"] is True, report
    assert "session_start_hook" in report["cursor_modules"]
    assert "session_stop_hook" in report["cursor_modules"]
    assert "pre_tool_hook" in report["cursor_modules"]
