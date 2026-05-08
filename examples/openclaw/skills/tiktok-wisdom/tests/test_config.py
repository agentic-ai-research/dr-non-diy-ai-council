"""TOML config loading and CLI-flag precedence."""
import sys
import tomllib
from pathlib import Path

import pytest
from build import load_config_file


SKILL_ROOT = Path(__file__).resolve().parent.parent
CONFIGS_DIR = SKILL_ROOT / "configs"


def test_free_tier_config_loads():
    cfg = load_config_file(CONFIGS_DIR / "free-tier-mac-say.toml")
    assert cfg["voice_provider"] == "mac-say"
    assert cfg["voice_id"] == "Daniel"
    assert cfg["no_push"] is True


def test_elevenlabs_config_loads():
    cfg = load_config_file(CONFIGS_DIR / "elevenlabs-strict-blog.toml")
    assert cfg["voice_provider"] == "eleven"
    assert cfg["strict"] is True
    assert cfg["persona"] == "bangkok-architect"


def test_listicle_persona_config_loads():
    cfg = load_config_file(CONFIGS_DIR / "persona-listicle.toml")
    assert cfg["voice_provider"] == "openai"
    assert cfg["voice_id"] == "onyx"
    assert cfg["style"] == "listicle"
    assert cfg["persona"] == "startup-founder"


def test_all_options_template_parses():
    """Template uses commented-out values everywhere; parses to a small dict."""
    cfg = load_config_file(CONFIGS_DIR / "all-options.toml")
    # Active (uncommented) values
    assert cfg["voice_provider"] == "mac-say"
    assert cfg["style"] == "auto"
    assert cfg["strict"] is False
    # Commented-out values absent
    assert "idea" not in cfg
    assert "context" not in cfg


def test_missing_config_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_config_file(tmp_path / "does-not-exist.toml")


def test_unknown_extension_raises(tmp_path: Path):
    bad = tmp_path / "config.yaml"
    bad.write_text("voice_provider: mac-say\n")
    with pytest.raises(RuntimeError, match="unsupported"):
        load_config_file(bad)


def test_json_config_works(tmp_path: Path):
    j = tmp_path / "cfg.json"
    j.write_text('{"voice_provider": "openai", "voice_id": "nova"}')
    cfg = load_config_file(j)
    assert cfg["voice_provider"] == "openai"
    assert cfg["voice_id"] == "nova"
