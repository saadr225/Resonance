from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import strawberry

from auth import AuthError, create_access_token, hash_password, verify_password
from config import settings
from db import (
    create_session,
    create_user,
    get_session,
    get_user_by_email,
    get_user_by_id,
    join_session,
    list_insights,
    list_sessions_for_user,
    list_transcripts,
    user_can_access_session,
)


@dataclass
class Context:
    pool: Any
    user_id: str | None


@strawberry.type
class User:
    id: str
    email: str


@strawberry.type
class AuthPayload:
    token: str
    user: User


@strawberry.type
class Session:
    id: str
    owner_id: str
    title: str
    invite_token: str


@strawberry.type
class Transcript:
    id: int
    session_id: str
    speaker_id: str
    text: str
    confidence: float
    ts_start: int
    ts_end: int


@strawberry.type
class Insight:
    id: int
    session_id: str
    summary: str
    action_items: list[str]
    sentiment: str
    generated_at: int


def _require_user(context: Context) -> str:
    if not context.user_id:
        raise AuthError("Authentication is required.")
    return context.user_id


def _session_from_record(record: Any) -> Session:
    return Session(
        id=record["id"],
        owner_id=record["owner_id"],
        title=record["title"],
        invite_token=record["invite_token"],
    )


def _json_list(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


@strawberry.type
class Query:
    @strawberry.field
    async def me(self, info) -> User | None:
        context: Context = info.context
        if not context.user_id:
            return None
        record = await get_user_by_id(context.pool, context.user_id)
        if not record:
            return None
        return User(id=record["id"], email=record["email"])

    @strawberry.field
    async def sessions(self, info) -> list[Session]:
        context: Context = info.context
        user_id = _require_user(context)
        return [_session_from_record(row) for row in await list_sessions_for_user(context.pool, user_id)]

    @strawberry.field
    async def session(self, info, session_id: str) -> Session | None:
        context: Context = info.context
        user_id = _require_user(context)
        if not await user_can_access_session(context.pool, user_id, session_id):
            return None
        record = await get_session(context.pool, session_id)
        return None if record is None else _session_from_record(record)

    @strawberry.field
    async def transcripts(self, info, session_id: str) -> list[Transcript]:
        context: Context = info.context
        user_id = _require_user(context)
        if not await user_can_access_session(context.pool, user_id, session_id):
            return []
        rows = await list_transcripts(context.pool, session_id)
        return [
            Transcript(
                id=row["id"],
                session_id=row["session_id"],
                speaker_id=row["speaker_id"],
                text=row["text"],
                confidence=float(row["confidence"]),
                ts_start=row["ts_start"],
                ts_end=row["ts_end"],
            )
            for row in rows
        ]

    @strawberry.field
    async def insights(self, info, session_id: str) -> list[Insight]:
        context: Context = info.context
        user_id = _require_user(context)
        if not await user_can_access_session(context.pool, user_id, session_id):
            return []
        rows = await list_insights(context.pool, session_id)
        return [
            Insight(
                id=row["id"],
                session_id=row["session_id"],
                summary=row["summary"],
                action_items=_json_list(row["action_items"]),
                sentiment=row["sentiment"],
                generated_at=row["generated_at"],
            )
            for row in rows
        ]


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def register(self, info, email: str, password: str) -> AuthPayload:
        password_hash = hash_password(password)
        user = await create_user(info.context.pool, email, password_hash)
        token = create_access_token(
            user_id=user["id"],
            email=user["email"],
            jwt_secret=settings.jwt_secret,
        )
        return AuthPayload(token=token, user=User(id=user["id"], email=user["email"]))

    @strawberry.mutation
    async def login(self, info, email: str, password: str) -> AuthPayload:
        user = await get_user_by_email(info.context.pool, email)
        if user is None or not verify_password(password, user["password_hash"]):
            raise AuthError("Invalid email or password.")
        token = create_access_token(
            user_id=user["id"],
            email=user["email"],
            jwt_secret=settings.jwt_secret,
        )
        return AuthPayload(token=token, user=User(id=user["id"], email=user["email"]))

    @strawberry.mutation
    async def create_room(self, info, title: str = "Untitled Resonance Session") -> Session:
        context: Context = info.context
        user_id = _require_user(context)
        session = await create_session(context.pool, user_id, title)
        return _session_from_record(session)

    @strawberry.mutation
    async def join_room(self, info, invite_token: str, display_name: str = "Guest") -> Session:
        context: Context = info.context
        session = await join_session(context.pool, invite_token, context.user_id, display_name)
        return _session_from_record(session)


schema = strawberry.Schema(query=Query, mutation=Mutation)
