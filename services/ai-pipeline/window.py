from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, DefaultDict


@dataclass(frozen=True)
class TranscriptLine:
    speaker_id: str
    text: str


class RollingTranscriptStore:
    def __init__(self, max_fragments: int = 40) -> None:
        self._windows: DefaultDict[str, Deque[TranscriptLine]] = defaultdict(lambda: deque(maxlen=max_fragments))

    def append(self, session_id: str, speaker_id: str, text: str) -> None:
        cleaned = " ".join(text.split())
        if cleaned:
            self._windows[session_id].append(TranscriptLine(speaker_id=speaker_id or "unknown", text=cleaned))

    def text_for(self, session_id: str) -> str:
        lines = self._windows.get(session_id, [])
        return "\n".join(f"{line.speaker_id}: {line.text}" for line in lines)

    def count(self, session_id: str) -> int:
        return len(self._windows.get(session_id, []))
