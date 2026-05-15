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


settings = Settings()
