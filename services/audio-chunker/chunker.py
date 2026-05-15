from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import redis.asyncio as redis
from redis.exceptions import ResponseError

try:
    import resonance_pb2 as pb
    import resonance_pb2_grpc as pb_grpc
except ModuleNotFoundError:
    @dataclass
    class _AudioChunk:
        session_id: str
        speaker_id: str
        pcm_data: bytes
        timestamp: int
        duration_ms: int

    class _ProtoFallback:
        AudioChunk = _AudioChunk

    pb = _ProtoFallback()
    pb_grpc = None


logger = logging.getLogger("resonance.audio-chunker")


def _read_field(data: dict[Any, Any], key: str, default: bytes = b"") -> bytes:
    if key in data:
        value = data[key]
    elif key.encode("utf-8") in data:
        value = data[key.encode("utf-8")]
    else:
        return default
    if isinstance(value, str):
        return value.encode("utf-8")
    return bytes(value)


def parse_audio_entry(session_id: str, data: dict[Any, Any]) -> pb.AudioChunk:
    timestamp = int(_read_field(data, "timestamp", _read_field(data, "ts", b"0")).decode("utf-8"))
    duration_ms = int(_read_field(data, "duration_ms", b"3000").decode("utf-8"))
    speaker_id = _read_field(data, "speaker_id", b"unknown").decode("utf-8")
    pcm_data = _read_field(data, "pcm", b"")
    return pb.AudioChunk(
        session_id=session_id,
        speaker_id=speaker_id,
        pcm_data=pcm_data,
        timestamp=timestamp,
        duration_ms=duration_ms,
    )


def transcript_to_json(fragment: pb.TranscriptFragment) -> str:
    return json.dumps(
        {
            "type": "transcript",
            "session_id": fragment.session_id,
            "speaker_id": fragment.speaker_id,
            "text": fragment.text,
            "confidence": fragment.confidence,
            "ts_start": fragment.ts_start,
            "ts_end": fragment.ts_end,
        }
    )


def _pending_message_id(entry: object) -> bytes | str | None:
    if hasattr(entry, "message_id"):
        return entry.message_id
    if hasattr(entry, "id"):
        return entry.id
    if isinstance(entry, dict):
        return entry.get("message_id") or entry.get("id")
    if isinstance(entry, (list, tuple)) and entry:
        return entry[0]
    return None


def _normalize_start_id(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


@dataclass
class SessionStreamer:
    redis_client: redis.Redis
    session_id: str
    ai_pipeline_addr: str
    consumer_group: str
    consumer_name: str
    retry_seconds: float = 2.0
    claim_idle_ms: int = 30000
    claim_batch_size: int = 20
    _claim_start_id: str = "0-0"
    _claim_supported: bool = True

    @property
    def stream_key(self) -> str:
        return f"audio:{self.session_id}"

    async def ensure_group(self) -> None:
        try:
            await self.redis_client.xgroup_create(
                self.stream_key,
                self.consumer_group,
                id="0",
                mkstream=True,
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def _claim_pending(self) -> list[tuple[Any, Any]]:
        if self.claim_idle_ms <= 0:
            return []
        if self._claim_supported:
            try:
                result = await self.redis_client.xautoclaim(
                    self.stream_key,
                    self.consumer_group,
                    self.consumer_name,
                    min_idle_time=self.claim_idle_ms,
                    start_id=self._claim_start_id,
                    count=self.claim_batch_size,
                )
            except ResponseError as exc:
                if "unknown command" in str(exc).lower():
                    self._claim_supported = False
                else:
                    raise
            else:
                next_start_id = result[0]
                entries = result[1]
                self._claim_start_id = _normalize_start_id(next_start_id or "0-0")
                return entries

        pending = await self.redis_client.xpending_range(
            self.stream_key,
            self.consumer_group,
            min="-",
            max="+",
            count=self.claim_batch_size,
            idle=self.claim_idle_ms,
        )
        if not pending:
            return []
        message_ids: list[bytes | str] = []
        for entry in pending:
            message_id = _pending_message_id(entry)
            if message_id is not None:
                message_ids.append(message_id)
        if not message_ids:
            return []
        return await self.redis_client.xclaim(
            self.stream_key,
            self.consumer_group,
            self.consumer_name,
            min_idle_time=self.claim_idle_ms,
            message_ids=message_ids,
        )

    async def audio_chunks(self):
        await self.ensure_group()
        while True:
            entries = await self._claim_pending()
            if entries:
                for message_id, data in entries:
                    chunk = parse_audio_entry(self.session_id, data)
                    yield chunk
                    await self.redis_client.xack(self.stream_key, self.consumer_group, message_id)
                continue
            streams = await self.redis_client.xreadgroup(
                self.consumer_group,
                self.consumer_name,
                streams={self.stream_key: ">"},
                count=1,
                block=1000,
            )
            if not streams:
                continue
            for _, entries in streams:
                for message_id, data in entries:
                    chunk = parse_audio_entry(self.session_id, data)
                    yield chunk
                    await self.redis_client.xack(self.stream_key, self.consumer_group, message_id)

    async def run(self) -> None:
        if pb_grpc is None:
            raise RuntimeError("resonance_pb2_grpc is missing. Run make proto or build the Docker image.")
        import grpc

        while True:
            try:
                async with grpc.aio.insecure_channel(self.ai_pipeline_addr) as channel:
                    stub = pb_grpc.AudioProcessorStub(channel)
                    async for fragment in stub.ProcessStream(self.audio_chunks()):
                        await self.redis_client.publish(
                            f"transcripts:{fragment.session_id}",
                            transcript_to_json(fragment),
                        )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Session streamer failed for %s; retrying", self.session_id)
                await asyncio.sleep(self.retry_seconds)


@dataclass
class SessionSupervisor:
    redis_client: redis.Redis
    ai_pipeline_addr: str
    consumer_group: str
    consumer_name: str
    scan_interval_seconds: float
    claim_idle_ms: int
    claim_batch_size: int
    tasks: dict[str, asyncio.Task] = field(default_factory=dict)

    async def discover_sessions(self) -> set[str]:
        sessions: set[str] = set()
        async for key in self.redis_client.scan_iter(match="audio:*"):
            key_text = key.decode("utf-8") if isinstance(key, bytes) else str(key)
            _, _, session_id = key_text.partition(":")
            if session_id:
                sessions.add(session_id)
        return sessions

    async def run(self) -> None:
        while True:
            sessions = await self.discover_sessions()
            for session_id in sessions:
                if session_id not in self.tasks or self.tasks[session_id].done():
                    streamer = SessionStreamer(
                        redis_client=self.redis_client,
                        session_id=session_id,
                        ai_pipeline_addr=self.ai_pipeline_addr,
                        consumer_group=self.consumer_group,
                        consumer_name=f"{self.consumer_name}-{session_id[:8]}",
                        claim_idle_ms=self.claim_idle_ms,
                        claim_batch_size=self.claim_batch_size,
                    )
                    self.tasks[session_id] = asyncio.create_task(streamer.run())
            await asyncio.sleep(self.scan_interval_seconds)

    async def stop(self) -> None:
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
