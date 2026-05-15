from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from os import getenv

import grpc
import redis.asyncio as redis

import resonance_pb2 as pb
import resonance_pb2_grpc as pb_grpc
from analyse import Analyzer, create_analyzer
from transcribe import MockTranscriber, WhisperTranscriber, create_transcriber
from window import RollingTranscriptStore


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("resonance.ai-pipeline")


@dataclass
class StreamProcessor(pb_grpc.AudioProcessorServicer):
    redis_client: redis.Redis
    transcriber: MockTranscriber | WhisperTranscriber
    analyzer: Analyzer
    analysis_interval_seconds: float = float(getenv("ANALYSIS_INTERVAL", "60.0"))
    windows: RollingTranscriptStore = field(default_factory=RollingTranscriptStore)
    last_analysis: dict[str, float] = field(default_factory=dict)
    analysis_tasks: dict[str, asyncio.Task] = field(default_factory=dict)
    analysis_pending: set[str] = field(default_factory=set)

    async def ProcessStream(self, request_iterator, context):
        async for chunk in request_iterator:
            result = await self.transcriber.transcribe(chunk.pcm_data)
            ts_start = chunk.timestamp
            ts_end = chunk.timestamp + max(chunk.duration_ms, 0)
            self.windows.append(chunk.session_id, chunk.speaker_id, result.text)

            fragment = pb.TranscriptFragment(
                session_id=chunk.session_id,
                speaker_id=chunk.speaker_id,
                text=result.text,
                confidence=result.confidence,
                ts_start=ts_start,
                ts_end=ts_end,
            )

            self._schedule_analysis(chunk.session_id)

            yield fragment

    def _analysis_due(self, session_id: str) -> bool:
        now = time.monotonic()
        previous = self.last_analysis.get(session_id, 0)
        if now - previous >= self.analysis_interval_seconds:
            self.last_analysis[session_id] = now
            return True
        return False

    def _schedule_analysis(self, session_id: str) -> None:
        if not self._analysis_due(session_id):
            return
        task = self.analysis_tasks.get(session_id)
        if task and not task.done():
            self.analysis_pending.add(session_id)
            return
        self.analysis_tasks[session_id] = asyncio.create_task(self._run_analysis(session_id))
        self.analysis_tasks[session_id].add_done_callback(
            lambda finished: self._analysis_done(session_id, finished)
        )

    def _analysis_done(self, session_id: str, task: asyncio.Task) -> None:
        self.analysis_tasks.pop(session_id, None)
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            logger.exception("LLM analysis task failed for session=%s", session_id)
        if session_id in self.analysis_pending:
            self.analysis_pending.discard(session_id)
            self.last_analysis[session_id] = time.monotonic()
            self.analysis_tasks[session_id] = asyncio.create_task(self._run_analysis(session_id))
            self.analysis_tasks[session_id].add_done_callback(
                lambda finished: self._analysis_done(session_id, finished)
            )

    async def _run_analysis(self, session_id: str) -> None:
        try:
            await self._publish_insight(session_id)
        except Exception:
            logger.exception("Insight publish failed for session=%s", session_id)

    async def _publish_insight(self, session_id: str) -> None:
        transcript = self.windows.text_for(session_id)
        try:
            insight = await self.analyzer.analyze(transcript)
        except Exception:
            logger.exception("LLM analysis failed; falling back to neutral insight")
            insight = await create_analyzer("mock").analyze(transcript)
        payload = {
            "type": "insight",
            "session_id": session_id,
            "summary": insight.summary,
            "action_items": insight.action_items,
            "sentiment": insight.sentiment,
            "generated_at": int(time.time() * 1000),
        }
        await self.redis_client.publish(f"insights:{session_id}", json.dumps(payload))


async def serve() -> None:
    redis_client = redis.from_url(getenv("REDIS_URL", "redis://localhost:6379"), decode_responses=True)
    server = grpc.aio.server()
    processor = StreamProcessor(
        redis_client=redis_client,
        transcriber=create_transcriber(),
        analyzer=create_analyzer(),
    )
    pb_grpc.add_AudioProcessorServicer_to_server(processor, server)
    listen_addr = f"0.0.0.0:{getenv('AI_PIPELINE_PORT', '50052')}"
    server.add_insecure_port(listen_addr)
    await server.start()
    logger.info("AI pipeline gRPC server listening on %s", listen_addr)
    try:
        await server.wait_for_termination()
    finally:
        await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(serve())
