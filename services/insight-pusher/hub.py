from __future__ import annotations

from collections import defaultdict
from typing import DefaultDict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._sessions: DefaultDict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._sessions[session_id].add(websocket)

    def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        self._sessions[session_id].discard(websocket)
        if not self._sessions[session_id]:
            self._sessions.pop(session_id, None)

    async def broadcast(self, session_id: str, message: str) -> int:
        delivered = 0
        for websocket in list(self._sessions.get(session_id, set())):
            try:
                await websocket.send_text(message)
                delivered += 1
            except Exception:
                self.disconnect(session_id, websocket)
        return delivered

    def connection_count(self, session_id: str) -> int:
        return len(self._sessions.get(session_id, set()))
