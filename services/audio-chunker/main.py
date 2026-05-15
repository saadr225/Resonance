from __future__ import annotations

import asyncio
import logging

import redis.asyncio as redis

from chunker import SessionSupervisor
from config import settings


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("resonance.audio-chunker")


async def main() -> None:
    redis_client = redis.from_url(settings.redis_url, decode_responses=False)
    supervisor = SessionSupervisor(
        redis_client=redis_client,
        ai_pipeline_addr=settings.ai_pipeline_addr,
        consumer_group=settings.consumer_group,
        consumer_name=settings.consumer_name,
        scan_interval_seconds=settings.session_scan_interval_seconds,
        claim_idle_ms=settings.claim_idle_ms,
        claim_batch_size=settings.claim_batch_size,
    )
    logger.info("Audio chunker watching Redis streams and sending chunks to %s", settings.ai_pipeline_addr)
    try:
        await supervisor.run()
    finally:
        await supervisor.stop()
        await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
