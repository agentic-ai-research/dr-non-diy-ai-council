"""Style auto-detection: 'three lessons…' → listicle, otherwise essay."""
import pytest
from build import detect_style


@pytest.mark.parametrize("idea", [
    "Three lessons I learned the hard way about money.",
    "Five things I wish someone told me at twenty-five.",
    "How to deal with people who don't believe in you.",
    "If I could go back and tell my younger self one thing…",
    "I learned the hard way that confidence is built by failing.",
    "3 ways founders sabotage themselves.",
    "What I wish I knew before raising my seed.",
    "Seven habits that ruined my twenties.",
])
def test_listicle_triggers(idea):
    assert detect_style(idea) == "listicle", f"expected listicle for: {idea!r}"


@pytest.mark.parametrize("idea", [
    "We chase clarity like it owes us something.",
    "When you can't sleep, the only honest thing to do is sit up and stop pretending.",
    "Most days the work is just showing up.",
    "What do you do when you feel unmotivated?",
    "Why reading the news every day is bad for you.",
    "The hidden cost of being available.",
])
def test_essay_default(idea):
    assert detect_style(idea) == "essay", f"expected essay for: {idea!r}"
