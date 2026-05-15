from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from strawberry.fastapi import GraphQLRouter

from auth import AuthError, create_access_token, decode_access_token, hash_password, verify_password
from config import settings
from db import create_pool, create_session, create_user, get_user_by_email, join_session, list_sessions_for_user
from schema import Context, schema


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class CreateSessionRequest(BaseModel):
    title: str = "Untitled Resonance Session"


class JoinSessionRequest(BaseModel):
    invite_token: str
    display_name: str = "Guest"


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


async def current_user_id(authorization: Annotated[str | None, Header()] = None) -> str:
    token = _bearer_token(authorization)
    if token is None:
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    try:
        return str(decode_access_token(token, settings.jwt_secret)["sub"])
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


async def graphql_context(request: Request) -> Context:
    token = _bearer_token(request.headers.get("authorization"))
    user_id = None
    if token:
        try:
            user_id = str(decode_access_token(token, settings.jwt_secret)["sub"])
        except AuthError:
            user_id = None
    return Context(pool=request.app.state.pool, user_id=user_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await create_pool(settings.postgres_dsn)
    try:
        yield
    finally:
        await app.state.pool.close()


app = FastAPI(
    title="Resonance Session API",
    description="Auth, room management, and historical GraphQL queries for Resonance.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

graphql_app = GraphQLRouter(schema, context_getter=graphql_context)
app.include_router(graphql_app, prefix="/graphql")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/register")
async def register(payload: RegisterRequest) -> dict[str, object]:
    password_hash = hash_password(payload.password)
    try:
        user = await create_user(app.state.pool, payload.email, password_hash)
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Email already registered.") from exc
    token = create_access_token(user_id=user["id"], email=user["email"], jwt_secret=settings.jwt_secret)
    return {"token": token, "user": {"id": user["id"], "email": user["email"]}}


@app.post("/auth/login")
async def login(payload: LoginRequest) -> dict[str, object]:
    user = await get_user_by_email(app.state.pool, payload.email)
    if user is None or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    token = create_access_token(user_id=user["id"], email=user["email"], jwt_secret=settings.jwt_secret)
    return {"token": token, "user": {"id": user["id"], "email": user["email"]}}


@app.post("/sessions")
async def create_room(payload: CreateSessionRequest, user_id: Annotated[str, Depends(current_user_id)]):
    session = await create_session(app.state.pool, user_id, payload.title)
    return dict(session)


@app.post("/sessions/join")
async def join_room(payload: JoinSessionRequest, authorization: Annotated[str | None, Header()] = None):
    token = _bearer_token(authorization)
    user_id = None
    if token:
        try:
            user_id = str(decode_access_token(token, settings.jwt_secret)["sub"])
        except AuthError:
            user_id = None
    try:
        session = await join_session(app.state.pool, payload.invite_token, user_id, payload.display_name)
        return dict(session)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ValueError, Exception) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/sessions")
async def sessions(user_id: Annotated[str, Depends(current_user_id)]):
    rows = await list_sessions_for_user(app.state.pool, user_id)
    return [dict(row) for row in rows]
