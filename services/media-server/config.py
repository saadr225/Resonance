from __future__ import annotations

from dataclasses import dataclass
from os import getenv


@dataclass(frozen=True)
class Settings:
    redis_url: str = getenv("REDIS_URL", "redis://localhost:6379")
    postgres_dsn: str = getenv(
        "POSTGRES_DSN",
        "postgresql://resonance:secret@localhost:5432/resonance",
    )
    jwt_secret: str = getenv("JWT_SECRET", "dev-secret")
    turn_server_url: str = getenv("TURN_SERVER_URL", "")
    turn_username: str = getenv("TURN_USERNAME", "")
    turn_credential: str = getenv("TURN_CREDENTIAL", "")
    chunk_ms: int = int(getenv("AUDIO_CHUNK_MS", "3000"))
    audio_stream_maxlen: int = int(getenv("AUDIO_STREAM_MAXLEN", "1200"))


settings = Settings()
