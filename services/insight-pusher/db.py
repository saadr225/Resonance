from __future__ import annotations

import json
from typing import Any

import asyncpg


async def create_pool(dsn: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=10)


async def user_can_access_session(pool: asyncpg.Pool, user_id: str, session_id: str) -> bool:
    value = await pool.fetchval(
        """
        SELECT EXISTS(
          SELECT 1
          FROM sessions s
          LEFT JOIN participants p ON p.session_id = s.id
          WHERE s.id = $1::uuid AND (s.owner_id = $2::uuid OR p.user_id = $2::uuid)
        )
        """,
        session_id,
        user_id,
    )
    return bool(value)


async def persist_insight(pool: asyncpg.Pool, payload: dict[str, Any]) -> None:
    action_items = payload.get("action_items", [])
    if not isinstance(action_items, list):
        action_items = []
    await pool.execute(
        """
        INSERT INTO insights (session_id, summary, action_items, sentiment, generated_at)
        VALUES ($1::uuid, $2, $3::jsonb, $4, $5)
        """,
        payload["session_id"],
        str(payload.get("summary", "")),
        json.dumps(action_items),
        payload.get("sentiment", "neutral"),
        int(payload.get("generated_at", 0)),
    )


async def persist_transcript(pool: asyncpg.Pool, payload: dict[str, Any]) -> None:
    await pool.execute(
        """
        INSERT INTO transcripts (session_id, speaker_id, text, confidence, ts_start, ts_end)
        VALUES ($1::uuid, $2, $3, $4, $5, $6)
        """,
        payload["session_id"],
        str(payload.get("speaker_id", "unknown")),
        str(payload.get("text", "")),
        float(payload.get("confidence", 0)),
        int(payload.get("ts_start", 0)),
        int(payload.get("ts_end", 0)),
    )
