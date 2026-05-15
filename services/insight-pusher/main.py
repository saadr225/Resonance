from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from auth import AuthError, decode_access_token
from config import settings
from db import create_pool, persist_insight, persist_transcript, user_can_access_session
from hub import ConnectionManager


manager = ConnectionManager()


async def redis_listener(app: FastAPI) -> None:
    pubsub = app.state.redis.pubsub()
    await pubsub.psubscribe("insights:*", "transcripts:*")
    try:
        async for message in pubsub.listen():
            if message.get("type") != "pmessage":
                continue
            channel = str(message["channel"])
            kind, _, session_id = channel.partition(":")
            payload_text = message["data"]
            try:
                payload = json.loads(payload_text)
                if kind == "insights":
                    await persist_insight(app.state.pool, payload)
                elif kind == "transcripts":
                    await persist_transcript(app.state.pool, payload)
            except Exception:
                payload = None
            await manager.broadcast(session_id, payload_text)
    finally:
        await pubsub.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await create_pool(settings.postgres_dsn)
    app.state.redis = redis.from_url(settings.redis_url, decode_responses=True)
    app.state.listener_task = asyncio.create_task(redis_listener(app))
    try:
        yield
    finally:
        app.state.listener_task.cancel()
        await asyncio.gather(app.state.listener_task, return_exceptions=True)
        await app.state.redis.aclose()
        await app.state.pool.close()


app = FastAPI(title="Resonance Insight Pusher", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str, token: str):
    try:
        payload = decode_access_token(token, settings.jwt_secret)
        allowed = await user_can_access_session(websocket.app.state.pool, str(payload["sub"]), session_id)
    except AuthError:
        allowed = False
    if not allowed:
        await websocket.close(code=1008)
        return

    await manager.connect(session_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(session_id, websocket)
    except Exception:
        manager.disconnect(session_id, websocket)
        await websocket.close(code=1011)
