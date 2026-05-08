"""Prompt files load from disk; persona overlay layers on base voice."""
from build import _load_prompt, load_persona, PROMPTS_DIR


def test_voice_preamble_loads():
    text = _load_prompt("voice-preamble.md")
    assert text, "voice-preamble.md must not be empty"
    assert "VOICE RULES" in text
    assert "ban" in text.lower()


def test_style_essay_loads():
    text = _load_prompt("style-essay.md")
    assert "ESSAY MODE" in text
    assert "visual_cues" in text


def test_style_listicle_loads():
    text = _load_prompt("style-listicle.md")
    assert "LISTICLE MODE" in text
    assert "HOOK" in text
    assert "KICKER" in text


def test_strict_addendum_loads():
    text = _load_prompt("strict-addendum.md")
    assert "STRICT-SOURCE MODE" in text
    assert "DO NOT INVENT" in text


def test_persona_plain_is_empty():
    """plain → no overlay (returns empty so the base voice is used as-is)."""
    assert load_persona("plain") == ""
    assert load_persona("") == ""
    assert load_persona("none") == ""


def test_persona_bangkok_architect():
    text = load_persona("bangkok-architect")
    assert text, "bangkok-architect persona must exist"
    assert "PERSONA OVERLAY" in text
    assert "Dr Non" in text
    assert "Harvard" in text


def test_persona_startup_founder():
    text = load_persona("startup-founder")
    assert text
    assert "PERSONA OVERLAY" in text
    assert "founder" in text.lower()


def test_persona_unknown_returns_empty():
    """Unknown persona names fall back to empty (no overlay)."""
    assert load_persona("nonexistent-persona-xyz") == ""


def test_prompts_dir_exists():
    assert PROMPTS_DIR.is_dir()
    assert (PROMPTS_DIR / "voice-preamble.md").exists()
    assert (PROMPTS_DIR / "personas").is_dir()
