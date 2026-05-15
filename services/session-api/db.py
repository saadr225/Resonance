from __future__ import annotations

import secrets
from typing import Any

import asyncpg


async def create_pool(dsn: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=10)


async def create_user(pool: asyncpg.Pool, email: str, password_hash: str) -> asyncpg.Record:
    return await pool.fetchrow(
        """
        INSERT INTO users (email, password_hash)
        VALUES ($1, $2)
        RETURNING id::text, email, created_at
        """,
        email.lower(),
        password_hash,
    )


async def get_user_by_email(pool: asyncpg.Pool, email: str) -> asyncpg.Record | None:
    return await pool.fetchrow(
        "SELECT id::text, email, password_hash, created_at FROM users WHERE email = $1",
        email.lower(),
    )


async def get_user_by_id(pool: asyncpg.Pool, user_id: str) -> asyncpg.Record | None:
    return await pool.fetchrow(
        "SELECT id::text, email, created_at FROM users WHERE id = $1::uuid",
        user_id,
    )


async def create_session(pool: asyncpg.Pool, owner_id: str, title: str) -> asyncpg.Record:
    invite_token = secrets.token_urlsafe(24)
    async with pool.acquire() as conn:
        async with conn.transaction():
            session = await conn.fetchrow(
                """
                INSERT INTO sessions (owner_id, title, invite_token)
                VALUES ($1::uuid, $2, $3)
                RETURNING id::text, owner_id::text, title, invite_token, created_at, ended_at
                """,
                owner_id,
                title,
                invite_token,
            )
            await conn.execute(
                """
                INSERT INTO participants (session_id, user_id, display_name)
                VALUES ($1::uuid, $2::uuid, $3)
                """,
                session["id"],
                owner_id,
                "Owner",
            )
            return session


async def join_session(
    pool: asyncpg.Pool,
    invite_token: str,
    user_id: str | None,
    display_name: str,
) -> asyncpg.Record:
    async with pool.acquire() as conn:
        session = await conn.fetchrow(
            """
            SELECT id::text, owner_id::text, title, invite_token, created_at, ended_at
            FROM sessions
            WHERE invite_token = $1 AND ended_at IS NULL
            """,
            invite_token,
        )
        if session is None:
            raise LookupError("Session invite token was not found.")
        await conn.execute(
            """
            INSERT INTO participants (session_id, user_id, display_name)
            VALUES ($1::uuid, $2::uuid, $3)
            """,
            session["id"],
            user_id,
            display_name,
        )
        return session


async def list_sessions_for_user(pool: asyncpg.Pool, user_id: str) -> list[asyncpg.Record]:
    return await pool.fetch(
        """
        SELECT DISTINCT s.id::text, s.owner_id::text, s.title, s.invite_token, s.created_at, s.ended_at
        FROM sessions s
        LEFT JOIN participants p ON p.session_id = s.id
        WHERE s.owner_id = $1::uuid OR p.user_id = $1::uuid
        ORDER BY s.created_at DESC
        """,
        user_id,
    )


async def get_session(pool: asyncpg.Pool, session_id: str) -> asyncpg.Record | None:
    return await pool.fetchrow(
        """
        SELECT id::text, owner_id::text, title, invite_token, created_at, ended_at
        FROM sessions
        WHERE id = $1::uuid
        """,
        session_id,
    )


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


async def list_transcripts(pool: asyncpg.Pool, session_id: str) -> list[asyncpg.Record]:
    return await pool.fetch(
        """
        SELECT id, session_id::text, speaker_id, text, confidence, ts_start, ts_end, created_at
        FROM transcripts
        WHERE session_id = $1::uuid
        ORDER BY ts_start ASC
        """,
        session_id,
    )


async def list_insights(pool: asyncpg.Pool, session_id: str) -> list[asyncpg.Record]:
    return await pool.fetch(
        """
        SELECT id, session_id::text, summary, action_items, sentiment, generated_at, created_at
        FROM insights
        WHERE session_id = $1::uuid
        ORDER BY generated_at ASC
        """,
        session_id,
    )


def record_to_dict(record: asyncpg.Record | None) -> dict[str, Any] | None:
    return None if record is None else dict(record)
