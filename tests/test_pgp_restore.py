"""pgp.restore_signed_content — content+.sig rollback for trust-root writers."""

from willow_mcp import pgp


def test_restore_signed_content_removes_fresh_pair(tmp_path):
    path = tmp_path / "manifest.json"
    sig = tmp_path / "manifest.json.sig"
    path.write_text('{"new": true}\n')
    sig.write_bytes(b"PARTIAL")
    pgp.restore_signed_content(path, None, None)
    assert not path.exists()
    assert not sig.exists()


def test_restore_signed_content_restores_prior_pair(tmp_path):
    path = tmp_path / "manifest.json"
    sig = tmp_path / "manifest.json.sig"
    path.write_text('{"new": true}\n')
    sig.write_bytes(b"PARTIAL")
    pgp.restore_signed_content(path, '{"old": true}\n', b"PRIOR")
    assert path.read_text() == '{"old": true}\n'
    assert sig.read_bytes() == b"PRIOR"


def test_restore_signed_content_drops_sig_when_prior_had_none(tmp_path):
    path = tmp_path / "manifest.json"
    sig = tmp_path / "manifest.json.sig"
    path.write_text('{"new": true}\n')
    sig.write_bytes(b"PARTIAL")
    pgp.restore_signed_content(path, '{"old": true}\n', None)
    assert path.read_text() == '{"old": true}\n'
    assert not sig.exists()
