from __future__ import annotations

from window import RollingTranscriptStore


def test_rolling_window_keeps_recent_fragments() -> None:
    store = RollingTranscriptStore(max_fragments=2)

    store.append("s1", "a", "hello")
    store.append("s1", "b", "there")
    store.append("s1", "a", "again")

    assert store.count("s1") == 2
    assert store.text_for("s1") == "b: there\na: again"
