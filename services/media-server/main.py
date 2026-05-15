from __future__ import annotations

from contextlib import asynccontextmanager

import redis.asyncio as redis
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from auth import AuthError, decode_access_token
from config import settings
from db import create_pool, user_can_access_session
from signaling import close_all_peers, create_peer_answer, handle_signaling_websocket, ice_server_entries


class OfferRequest(BaseModel):
    session_id: str
    token: str
    sdp: str
    type: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = redis.from_url(settings.redis_url, decode_responses=False)
    app.state.pool = await create_pool(settings.postgres_dsn)
    try:
        yield
    finally:
        await close_all_peers()
        await app.state.redis.aclose()
        await app.state.pool.close()


app = FastAPI(
    title="Resonance Media Server",
    description=(
        "aiortc WebRTC ingress with a server-side PCM tap. This uses DTLS-SRTP "
        "transport encryption to the server, not true end-to-end encryption."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ice")
async def ice() -> dict[str, list[dict[str, Any]]]:
    return {"iceServers": ice_server_entries()}


@app.post("/offer")
async def offer(payload: OfferRequest) -> dict[str, str]:
    try:
        token_payload = decode_access_token(payload.token, settings.jwt_secret)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    user_id = str(token_payload["sub"])
    try:
        allowed = await user_can_access_session(app.state.pool, user_id, payload.session_id)
    except Exception:
        allowed = False
    if not allowed:
        raise HTTPException(status_code=403, detail="Not authorized for session.")

    return await create_peer_answer(
        session_id=payload.session_id,
        speaker_id=user_id,
        sdp=payload.sdp,
        offer_type=payload.type,
        redis_client=app.state.redis,
    )


@app.websocket("/ws/{session_id}")
async def signaling_ws(websocket: WebSocket, session_id: str) -> None:
    token = websocket.query_params.get("token", "")
    try:
        token_payload = decode_access_token(token, settings.jwt_secret)
        user_id = str(token_payload["sub"])
        allowed = await user_can_access_session(websocket.app.state.pool, user_id, session_id)
    except AuthError:
        allowed = False
    except Exception:
        allowed = False
    if not allowed:
        await websocket.close(code=1008)
        return

    await handle_signaling_websocket(
        session_id=session_id,
        speaker_id=user_id,
        ws=websocket,
        redis_client=app.state.redis,
    )
