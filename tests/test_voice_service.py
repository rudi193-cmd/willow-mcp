from pathlib import Path

import pytest

from willow_mcp import voice_service as vs


@pytest.fixture
def config(tmp_path):
    return vs.VoiceServiceConfig(
        python=Path("/opt/willow-mcp/bin/python"),
        workdir=tmp_path / "checkout",
        willow_home=tmp_path / "home",
        app_id="voice-host",
        wake_models="/models/willow.onnx",
        kokoro_url="http://localhost:5000/v1/audio/speech",
        kokoro_voice="am_michael",
        handler="myapp.voice:handle",
    )


def test_render_unit_includes_voice_extra_handler(config):
    unit = vs.render_unit(config)
    assert "--handler myapp.voice:handle" in unit
    assert "@" not in unit


def test_render_unit_defaults_to_echo_without_handler(tmp_path):
    cfg = vs.VoiceServiceConfig(
        python=Path("/usr/bin/python3"),
        workdir=tmp_path,
        willow_home=tmp_path / "home",
        app_id="willow",
        wake_models="/models/willow.onnx",
        kokoro_url="http://localhost:5000/v1/audio/speech",
        kokoro_voice="am_michael",
        handler="",
    )
    unit = vs.render_unit(cfg)
    assert "--echo" in unit
    assert "--handler" not in unit


def test_install_requires_wake_models(tmp_path):
    cfg = vs.VoiceServiceConfig(
        python=Path("/usr/bin/python3"),
        workdir=tmp_path,
        willow_home=tmp_path / "home",
        app_id="willow",
        wake_models="",
        kokoro_url="http://localhost:5000/v1/audio/speech",
        kokoro_voice="am_michael",
        handler="",
    )
    result = vs.install(cfg)
    assert "error" in result


def test_repository_and_packaged_voice_templates_match():
    repository = (
        Path(__file__).resolve().parents[1] / "deploy" / vs.template_path().name
    )
    assert repository.read_text() == vs.template_path().read_text()
