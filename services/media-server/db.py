from __future__ import annotations

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
