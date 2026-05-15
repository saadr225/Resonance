from __future__ import annotations

from chunker import parse_audio_entry, transcript_to_json


class Fragment:
    session_id = "s1"
    speaker_id = "u1"
    text = "hello"
    confidence = 0.9
    ts_start = 1000
    ts_end = 4000


def test_parse_audio_entry_accepts_byte_fields() -> None:
    chunk = parse_audio_entry(
        "s1",
        {
            b"speaker_id": b"u1",
            b"pcm": b"\x00\x01",
            b"timestamp": b"123",
            b"duration_ms": b"3000",
        },
    )

    assert chunk.session_id == "s1"
    assert chunk.speaker_id == "u1"
    assert chunk.pcm_data == b"\x00\x01"
    assert chunk.timestamp == 123


def test_transcript_json_includes_type() -> None:
    payload = transcript_to_json(Fragment())

    assert '"type": "transcript"' in payload
    assert '"text": "hello"' in payload
