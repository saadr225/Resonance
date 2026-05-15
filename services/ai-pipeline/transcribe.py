from __future__ import annotations

import asyncio
from dataclasses import dataclass
from os import getenv

import numpy as np


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    confidence: float


class MockTranscriber:
    async def transcribe(self, pcm_data: bytes) -> TranscriptionResult:
        if not pcm_data:
            return TranscriptionResult(text="", confidence=0.0)
        return TranscriptionResult(text="Mock transcript fragment from live audio.", confidence=0.99)


class WhisperTranscriber:
    def __init__(self, model_name: str, device: str = "cpu", compute_type: str = "int8") -> None:
        from faster_whisper import WhisperModel

        self._model = WhisperModel(model_name, device=device, compute_type=compute_type)

    async def transcribe(self, pcm_data: bytes) -> TranscriptionResult:
        audio = pcm48_to_float16k(pcm_data)
        if audio.size == 0:
            return TranscriptionResult(text="", confidence=0.0)
        return await asyncio.to_thread(self._transcribe_sync, audio)

    def _transcribe_sync(self, audio: np.ndarray) -> TranscriptionResult:
        segments, _ = self._model.transcribe(audio, beam_size=1, language="en", condition_on_previous_text=False, vad_filter=True)
        texts: list[str] = []
        confidences: list[float] = []
        for segment in segments:
            text = segment.text.strip()
            if text:
                texts.append(text)
            avg_logprob = getattr(segment, "avg_logprob", None)
            if avg_logprob is not None:
                confidences.append(max(0.0, min(1.0, float(np.exp(avg_logprob)))))
        confidence = sum(confidences) / len(confidences) if confidences else 0.85
        return TranscriptionResult(text=" ".join(texts), confidence=confidence)


def pcm48_to_float16k(pcm_data: bytes) -> np.ndarray:
    samples = np.frombuffer(pcm_data, dtype="<i2")
    if samples.size == 0:
        return np.array([], dtype=np.float32)
    downsampled = samples[::3]
    return (downsampled.astype(np.float32) / 32768.0).copy()


def create_transcriber() -> MockTranscriber | WhisperTranscriber:
    model_name = getenv("WHISPER_MODEL", "base.en")
    if model_name.lower() == "mock":
        return MockTranscriber()
    return WhisperTranscriber(
        model_name=model_name,
        device=getenv("WHISPER_DEVICE", "cpu"),
        compute_type=getenv("WHISPER_COMPUTE_TYPE", "int8"),
    )
