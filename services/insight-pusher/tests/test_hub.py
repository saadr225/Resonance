from __future__ import annotations

import pytest

from hub import ConnectionManager


class FakeWebSocket:
    def __init__(self, fail: bool = False) -> None:
        self.accepted = False
        self.messages: list[str] = []
        self.fail = fail

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, message: str) -> None:
        if self.fail:
            raise RuntimeError("send failed")
        self.messages.append(message)


@pytest.mark.asyncio
async def test_broadcast_drops_failed_sockets() -> None:
    manager = ConnectionManager()
    good = FakeWebSocket()
    bad = FakeWebSocket(fail=True)

    await manager.connect("s1", good)
    await manager.connect("s1", bad)
    delivered = await manager.broadcast("s1", '{"summary":"ok"}')

    assert delivered == 1
    assert good.messages == ['{"summary":"ok"}']
    assert manager.connection_count("s1") == 1
