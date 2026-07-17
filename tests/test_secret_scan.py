"""Egress secret redaction — the unit contract for secret_scan.redact_egress.

These are the adversarial fixtures the funnel relies on: a credential of each
supported FORMAT smuggled through the data path is redacted, structure and
non-secret data survive, the reported kinds never carry the value, and
legitimate near-misses (a credential SOURCE, an ordinary id) are left alone.
"""
from willow_mcp import secret_scan


AWS_KEY = "AKIA" + "Q" * 16
PROVIDER_KEY = "sk-ant-" + "a1B2c3D4" * 4
GITHUB_TOKEN = "ghp_" + "b" * 36
SLACK_TOKEN = "xoxb-123456789012-abcdefABCDEF"
GOOGLE_KEY = "AIza" + "C" * 35
STRIPE_KEY = "sk_live_" + "d" * 24
JWT = "eyJhbGciOiJI.eyJzdWIiOiIx.QsWn3kF9aa"
PRIVATE_KEY = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQ==\n"
    "-----END OPENSSH PRIVATE KEY-----"
)


def test_aws_access_key_is_redacted():
    out, kinds = secret_scan.redact_egress({"note": f"key is {AWS_KEY} ok"})
    assert AWS_KEY not in out["note"]
    assert "[REDACTED:aws_access_key_id]" in out["note"]
    assert kinds == ["aws_access_key_id"]


def test_provider_api_key_is_redacted():
    out, kinds = secret_scan.redact_egress({"v": PROVIDER_KEY})
    assert PROVIDER_KEY not in out["v"]
    assert kinds == ["provider_api_key"]


def test_private_key_block_is_redacted_whole():
    out, kinds = secret_scan.redact_egress(PRIVATE_KEY)
    assert "PRIVATE KEY" not in out
    assert "b3BlbnNz" not in out          # the base64 body is gone too
    assert kinds == ["private_key"]


def test_github_slack_google_stripe_jwt_each_redacted():
    for secret, kind in [
        (GITHUB_TOKEN, "github_token"),
        (SLACK_TOKEN, "slack_token"),
        (GOOGLE_KEY, "google_api_key"),
        (STRIPE_KEY, "stripe_key"),
        (JWT, "jwt"),
    ]:
        out, kinds = secret_scan.redact_egress({"body": f"x {secret} y"})
        assert secret not in out["body"], kind
        assert kinds == [kind]


def test_redaction_walks_nested_structures():
    payload = {"rows": [{"blob": f"pre {AWS_KEY} post"}, {"ok": "harmless"}],
               "meta": {"deep": {"tok": PROVIDER_KEY}}}
    out, kinds = secret_scan.redact_egress(payload)
    assert AWS_KEY not in str(out)
    assert PROVIDER_KEY not in str(out)
    assert out["rows"][1]["ok"] == "harmless"        # non-secret untouched
    assert set(kinds) == {"aws_access_key_id", "provider_api_key"}


def test_reported_kinds_never_contain_the_value():
    _, kinds = secret_scan.redact_egress({"v": AWS_KEY})
    assert all(AWS_KEY not in k for k in kinds)       # audit trail is payload-free


def test_non_string_scalars_pass_through():
    out, kinds = secret_scan.redact_egress({"n": 42, "b": True, "z": None})
    assert out == {"n": 42, "b": True, "z": None}
    assert kinds == []


def test_credential_source_is_not_a_secret():
    # `credential_source()` returns strings like "env:OPENAI_API_KEY" — a name,
    # not a value. The backstop must not redact the source it points to.
    out, kinds = secret_scan.redact_egress({"source": "env:OPENAI_API_KEY",
                                            "via": "vault"})
    assert out == {"source": "env:OPENAI_API_KEY", "via": "vault"}
    assert kinds == []


def test_ordinary_ids_are_not_false_positives():
    # UUIDs, sha hashes, and record ids must survive — precision over recall.
    payload = {"id": "9f8c2b10-4e3a-4d21-bb0e-2a1c9d6e7f00",
               "sha": "a" * 40, "record_id": "agents:42"}
    out, kinds = secret_scan.redact_egress(payload)
    assert out == payload
    assert kinds == []


def test_clean_result_is_returned_unchanged():
    payload = {"id": "notes:1", "action": "created", "count": 3}
    out, kinds = secret_scan.redact_egress(payload)
    assert out == payload
    assert kinds == []
