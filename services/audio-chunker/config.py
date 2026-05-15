from __future__ import annotations

from dataclasses import dataclass
from os import getenv


@dataclass(frozen=True)
class Settings:
    redis_url: str = getenv("REDIS_URL", "redis://localhost:6379")
    ai_pipeline_addr: str = getenv("AI_PIPELINE_ADDR", "localhost:50052")
    consumer_group: str = getenv("AUDIO_CONSUMER_GROUP", "audio-chunker")
    consumer_name: str = getenv("AUDIO_CONSUMER_NAME", "chunker-1")
    session_scan_interval_seconds: float = float(getenv("SESSION_SCAN_INTERVAL_SECONDS", "2"))
    claim_idle_ms: int = int(getenv("AUDIO_CLAIM_IDLE_MS", "30000"))
    claim_batch_size: int = int(getenv("AUDIO_CLAIM_BATCH", "20"))


settings = Settings()
