"""Tests for mcp_adapters — advisory-only downstream tool classification."""
from willow_mcp import mcp_adapters


def test_classify_destructive_wins_over_read_in_a_mixed_name():
    assert mcp_adapters.classify_tool("list_and_delete_stale") == "destructive"


def test_classify_read():
    assert mcp_adapters.classify_tool("list_files") == "read"
    assert mcp_adapters.classify_tool("get_status") == "read"


def test_classify_write():
    assert mcp_adapters.classify_tool("create_issue") == "write"
    assert mcp_adapters.classify_tool("send_message") == "write"


def test_classify_destructive():
    assert mcp_adapters.classify_tool("delete_repo") == "destructive"
    assert mcp_adapters.classify_tool("terminate_session") == "destructive"


def test_classify_unknown_falls_back_to_unknown():
    assert mcp_adapters.classify_tool("frobnicate") == "unknown"


def test_classify_falls_back_to_description_when_name_is_uninformative():
    assert mcp_adapters.classify_tool("tool_seven", "permanently deletes the record") == "destructive"
    assert mcp_adapters.classify_tool("tool_seven", "lists all open records") == "read"


def test_classify_stem_matching_also_catches_noun_forms():
    """The truncated stem ("delet", not "delete") catches "deletion" too, not
    only verb inflections — an over-cautious "destructive" is the safer
    direction for an advisory classifier to err in."""
    assert mcp_adapters.classify_tool("get_status", "reports whether a deletion job is scheduled") == "destructive"


def test_classify_stem_matching_can_false_positive_and_that_is_the_documented_tradeoff():
    """"deleterious" shares the "delet" stem with "delete" but is an
    unrelated word — this module's own docstring says the guess can be
    wrong in either direction; this is the concrete shape of wrong-toward-
    caution, which is the direction an advisory-only classifier should err."""
    assert mcp_adapters.classify_tool("describe_health", "reports deleterious side effects") == "destructive"


def test_classify_matches_inflected_forms_of_a_recognized_stem():
    assert mcp_adapters.classify_tool("x", "this deletes every matching row") == "destructive"
    assert mcp_adapters.classify_tool("x", "removing stale entries") == "destructive"


def test_default_payload_shape():
    payload = mcp_adapters.default_payload("srv1", "delete_repo", {"name": "x"}, "destructive")
    assert payload["kind"] == "federated_mcp_call"
    assert "destructive" in payload["summary"]
    assert payload["payload"]["server_id"] == "srv1"
    assert payload["payload"]["tool"] == "delete_repo"
    assert payload["payload"]["arguments"] == {"name": "x"}


def test_default_payload_handles_none_arguments():
    payload = mcp_adapters.default_payload("srv1", "t", None, "write")
    assert payload["payload"]["arguments"] == {}
