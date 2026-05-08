"""Cache layer: hash determinism, hit/miss, scoped invalidation."""
from pathlib import Path
import pytest
from lib import cache


def test_hash_inputs_deterministic():
    """Same inputs in same order → same hash."""
    a = cache.hash_inputs("script", "idea text", "essay", False, "plain")
    b = cache.hash_inputs("script", "idea text", "essay", False, "plain")
    assert a == b
    assert len(a) == 16   # 16-char hex truncation


def test_hash_inputs_changes_on_input_change():
    base = cache.hash_inputs("tts", "hello world", "mac-say", "Daniel")
    assert base != cache.hash_inputs("tts", "hello WORLD", "mac-say", "Daniel")
    assert base != cache.hash_inputs("tts", "hello world", "openai", "Daniel")
    assert base != cache.hash_inputs("tts", "hello world", "mac-say", "Karen")


def test_hash_inputs_handles_lists_and_dicts():
    """Cues are list-of-dicts; corpus paths are list-of-strings; both
    must produce stable hashes."""
    cues = [{"timestamp_pct": 0.0, "query": "rain"},
            {"timestamp_pct": 0.5, "query": "city"}]
    a = cache.hash_inputs("art", cues, ["a.jpg", "b.jpg"])
    b = cache.hash_inputs("art", cues, ["a.jpg", "b.jpg"])
    assert a == b


def test_cache_check_miss_when_no_file(tmp_path: Path):
    out = tmp_path / "voice.mp3"
    assert cache.cache_check(out, "anykey") is False


def test_cache_save_then_check(tmp_path: Path):
    out = tmp_path / "voice.mp3"
    out.write_bytes(b"fake-audio")
    cache.cache_save(out, "abcdef0123")
    assert cache.cache_check(out, "abcdef0123") is True
    assert cache.cache_check(out, "different") is False


def test_cache_check_dir_round_trip(tmp_path: Path):
    art_dir = tmp_path / "art"
    art_dir.mkdir()
    (art_dir / "composite-00.jpg").write_bytes(b"fake-image")
    cache.cache_save_dir(art_dir, "key-abc")
    assert cache.cache_check_dir(art_dir, "key-abc") is True
    assert cache.cache_check_dir(art_dir, "key-xyz") is False


def test_invalidate_from_only_kills_downstream(tmp_path: Path):
    """`invalidate_from('tts', ...)` should remove keys for tts/video/captions/final
    but leave script and art keys intact."""
    work = tmp_path / "work"
    work.mkdir()
    (work / "art").mkdir()
    # Set up keys for every stage
    plan = work / "plan.json";              plan.write_text("{}")
    art_dir = work / "art"
    voice = work / "voice.mp3";             voice.write_bytes(b"a")
    raw_v = work / "video-raw.mp4";         raw_v.write_bytes(b"a")
    cap_v = work / "video-captioned.mp4";   cap_v.write_bytes(b"a")
    final = tmp_path / "wisdom-001.mp4";    final.write_bytes(b"a")

    cache.cache_save(plan,  "k-script")
    cache.cache_save_dir(art_dir, "k-art")
    cache.cache_save(voice, "k-tts")
    cache.cache_save(raw_v, "k-video")
    cache.cache_save(cap_v, "k-cap")
    cache.cache_save(final, "k-final")

    stage_outputs = {
        "script":   plan,
        "art":      art_dir,
        "tts":      voice,
        "video":    raw_v,
        "captions": cap_v,
        "final":    final,
    }
    cache.invalidate_from("tts", stage_outputs)

    # Upstream survives
    assert cache.cache_check(plan, "k-script") is True
    assert cache.cache_check_dir(art_dir, "k-art") is True
    # Target + downstream invalidated
    assert cache.cache_check(voice, "k-tts") is False
    assert cache.cache_check(raw_v, "k-video") is False
    assert cache.cache_check(cap_v, "k-cap") is False
    assert cache.cache_check(final, "k-final") is False


def test_invalidate_from_unknown_stage_raises():
    with pytest.raises(ValueError):
        cache.invalidate_from("not-a-real-stage", {})


def test_stages_in_order_complete():
    """The ordered stage list defines the invalidation cascade. If
    new stages are added, they must be added here too."""
    expected = ("context", "script", "art", "tts", "video", "captions", "final")
    assert cache.STAGES_IN_ORDER == expected
