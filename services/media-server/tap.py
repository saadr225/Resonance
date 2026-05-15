from __future__ import annotations

import time

from aiortc import MediaStreamTrack
from av import AudioFrame
from av.audio.resampler import AudioResampler


class AudioTapTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(
        self,
        track: MediaStreamTrack,
        session_id: str,
        speaker_id: str,
        redis_client,
        chunk_ms: int = 3000,
        maxlen: int = 1200,
    ) -> None:
        super().__init__()
        self._track = track
        self._resampler = AudioResampler(format="s16", layout="mono", rate=48000)
        self.session_id = session_id
        self.speaker_id = speaker_id
        self.redis = redis_client
        self.chunk_ms = chunk_ms
        self.maxlen = maxlen
        self._buffer = bytearray()
        self._buffer_ms = 0.0

    async def recv(self) -> AudioFrame:
        frame: AudioFrame = await self._track.recv()
        for pcm_frame in self._resampler.resample(frame):
            pcm = pcm_frame.to_ndarray().tobytes()
            self._buffer.extend(pcm)
            self._buffer_ms += (pcm_frame.samples / pcm_frame.sample_rate) * 1000
        if self._buffer_ms >= self.chunk_ms:
            await self.flush()
        return frame

    async def flush(self) -> None:
        if not self._buffer:
            return
        fields = {
            "session_id": self.session_id,
            "speaker_id": self.speaker_id,
            "pcm": bytes(self._buffer),
            "timestamp": str(int(time.time() * 1000)),
            "duration_ms": str(self.chunk_ms),
        }
        if self.maxlen > 0:
            await self.redis.xadd(
                f"audio:{self.session_id}",
                fields,
                maxlen=self.maxlen,
                approximate=True,
            )
        else:
            await self.redis.xadd(
                f"audio:{self.session_id}",
                fields,
            )
        self._buffer.clear()
        self._buffer_ms = 0.0


async def drain_tap(tap_track: AudioTapTrack) -> None:
    while True:
        await tap_track.recv()
