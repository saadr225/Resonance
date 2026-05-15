from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from aiortc import (
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCRtpSender,
    RTCSessionDescription,
)
from aiortc.contrib.media import MediaRelay
from aiortc.sdp import candidate_from_sdp
from fastapi import WebSocket, WebSocketDisconnect

from config import settings
from tap import AudioTapTrack, drain_tap


logger = logging.getLogger("resonance.media-server")
relay = MediaRelay()


@dataclass
class RoomTrack:
    track: object
    speaker_id: str


@dataclass(eq=False)
class PeerState:
    pc: RTCPeerConnection
    session_id: str
    speaker_id: str
    ws: WebSocket
    tap_tasks: set[asyncio.Task]
    outbound_senders: dict[object, RTCRtpSender] = field(default_factory=dict)
    pending_renegotiate: bool = False
    negotiation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    closed: bool = False


rooms: defaultdict[str, list[RoomTrack]] = defaultdict(list)
session_peers: defaultdict[str, list[PeerState]] = defaultdict(list)
peer_connections: set[RTCPeerConnection] = set()


def _parse_ice_urls(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def ice_server_entries() -> list[dict[str, Any]]:
    urls = _parse_ice_urls(settings.turn_server_url)
    if not urls:
        return []
    entry: dict[str, Any] = {"urls": urls if len(urls) > 1 else urls[0]}
    if settings.turn_username:
        entry["username"] = settings.turn_username
    if settings.turn_credential:
        entry["credential"] = settings.turn_credential
    return [entry]


def rtc_configuration() -> RTCConfiguration:
    ice_servers: list[RTCIceServer] = []
    for entry in ice_server_entries():
        ice_servers.append(
            RTCIceServer(
                urls=entry["urls"],
                username=entry.get("username"),
                credential=entry.get("credential"),
            )
        )
    return RTCConfiguration(iceServers=ice_servers)


async def _safe_ws_send(peer: PeerState, payload: dict[str, Any]) -> None:
    try:
        await peer.ws.send_json(payload)
    except RuntimeError:
        logger.warning("WebSocket not available for session=%s speaker=%s", peer.session_id, peer.speaker_id)
    except Exception:
        logger.exception("Failed to send signaling message for session=%s speaker=%s", peer.session_id, peer.speaker_id)


def _add_outbound_track(peer: PeerState, track: object, *, renegotiate: bool) -> None:
    if track in peer.outbound_senders:
        return
    sender = peer.pc.addTrack(relay.subscribe(track))
    peer.outbound_senders[track] = sender
    if renegotiate:
        peer.pending_renegotiate = True
        asyncio.create_task(_maybe_renegotiate(peer))


async def _maybe_renegotiate(peer: PeerState) -> None:
    if peer.closed or not peer.pending_renegotiate:
        return
    if peer.pc.signalingState != "stable":
        return
    async with peer.negotiation_lock:
        if peer.closed or not peer.pending_renegotiate:
            return
        if peer.pc.signalingState != "stable":
            return
        peer.pending_renegotiate = False
        try:
            offer = await peer.pc.createOffer()
            await peer.pc.setLocalDescription(offer)
            await _safe_ws_send(peer, {"type": "offer", "sdp": peer.pc.localDescription.sdp})
        except Exception:
            logger.exception("Failed to renegotiate session=%s speaker=%s", peer.session_id, peer.speaker_id)


async def _remove_room_track(session_id: str, track: object) -> None:
    rooms[session_id] = [item for item in rooms[session_id] if item.track is not track]
    for peer in list(session_peers[session_id]):
        sender = peer.outbound_senders.pop(track, None)
        if sender is None:
            continue
        peer.pc.removeTrack(sender)
        peer.pending_renegotiate = True
        asyncio.create_task(_maybe_renegotiate(peer))


async def _remove_speaker_tracks(session_id: str, speaker_id: str) -> None:
    tracks = [item.track for item in rooms[session_id] if item.speaker_id == speaker_id]
    for track in tracks:
        await _remove_room_track(session_id, track)


async def handle_signaling_websocket(
    *,
    session_id: str,
    speaker_id: str,
    ws: WebSocket,
    redis_client,
) -> None:
    await ws.accept()
    pc = RTCPeerConnection(configuration=rtc_configuration())
    peer_connections.add(pc)

    peer = PeerState(
        pc=pc,
        session_id=session_id,
        speaker_id=speaker_id,
        ws=ws,
        tap_tasks=set(),
    )
    session_peers[session_id].append(peer)

    for room_track in rooms[session_id]:
        if room_track.speaker_id != speaker_id:
            _add_outbound_track(peer, room_track.track, renegotiate=False)

    @pc.on("icecandidate")
    async def on_icecandidate(candidate):
        payload: dict[str, Any] = {"type": "candidate", "candidate": None}
        if candidate is not None:
            payload.update(
                {
                    "candidate": candidate.to_sdp(),
                    "sdpMid": candidate.sdpMid,
                    "sdpMLineIndex": candidate.sdpMLineIndex,
                }
            )
        await _safe_ws_send(peer, payload)

    @pc.on("signalingstatechange")
    async def on_signalingstatechange():
        await _maybe_renegotiate(peer)

    @pc.on("track")
    def on_track(track):
        logger.info("Received %s track for session=%s speaker=%s", track.kind, session_id, speaker_id)
        if track.kind != "audio":
            return
        rooms[session_id].append(RoomTrack(track=track, speaker_id=speaker_id))
        tap_track = AudioTapTrack(
            relay.subscribe(track),
            session_id=session_id,
            speaker_id=speaker_id,
            redis_client=redis_client,
            chunk_ms=settings.chunk_ms,
            maxlen=settings.audio_stream_maxlen,
        )
        task = asyncio.create_task(drain_tap(tap_track))
        peer.tap_tasks.add(task)
        task.add_done_callback(peer.tap_tasks.discard)

        for other_peer in list(session_peers[session_id]):
            if other_peer is peer:
                continue
            _add_outbound_track(other_peer, track, renegotiate=True)

        @track.on("ended")
        async def on_ended():
            await _remove_room_track(session_id, track)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        logger.info("Peer connection state changed to %s", pc.connectionState)
        if pc.connectionState in {"failed", "closed", "disconnected"}:
            await close_peer(peer)

    try:
        while True:
            message = await ws.receive_json()
            message_type = message.get("type")
            if message_type == "offer":
                await pc.setRemoteDescription(RTCSessionDescription(sdp=message["sdp"], type="offer"))
                answer = await pc.createAnswer()
                await pc.setLocalDescription(answer)
                await _safe_ws_send(peer, {"type": "answer", "sdp": pc.localDescription.sdp})
            elif message_type == "answer":
                await pc.setRemoteDescription(RTCSessionDescription(sdp=message["sdp"], type="answer"))
            elif message_type == "candidate":
                candidate = message.get("candidate")
                if candidate:
                    ice = candidate_from_sdp(candidate)
                    ice.sdpMid = message.get("sdpMid")
                    ice.sdpMLineIndex = message.get("sdpMLineIndex")
                    await pc.addIceCandidate(ice)
    except WebSocketDisconnect:
        logger.info("Signaling WebSocket disconnected for session=%s speaker=%s", session_id, speaker_id)
    except Exception:
        logger.exception("Signaling error for session=%s speaker=%s", session_id, speaker_id)
    finally:
        await close_peer(peer)


async def create_peer_answer(
    *,
    session_id: str,
    speaker_id: str,
    sdp: str,
    offer_type: str,
    redis_client,
) -> dict[str, str]:
    pc = RTCPeerConnection(configuration=rtc_configuration())
    peer_connections.add(pc)
    tap_tasks: set[asyncio.Task] = set()

    for room_track in rooms[session_id]:
        if room_track.speaker_id != speaker_id:
            pc.addTrack(relay.subscribe(room_track.track))

    @pc.on("track")
    def on_track(track):
        logger.info("Received %s track for session=%s speaker=%s", track.kind, session_id, speaker_id)
        if track.kind != "audio":
            return
        rooms[session_id].append(RoomTrack(track=track, speaker_id=speaker_id))
        for other_peer in list(session_peers[session_id]):
            if other_peer.speaker_id == speaker_id:
                continue
            _add_outbound_track(other_peer, track, renegotiate=True)
        tap_track = AudioTapTrack(
            relay.subscribe(track),
            session_id=session_id,
            speaker_id=speaker_id,
            redis_client=redis_client,
            chunk_ms=settings.chunk_ms,
            maxlen=settings.audio_stream_maxlen,
        )
        task = asyncio.create_task(drain_tap(tap_track))
        tap_tasks.add(task)
        task.add_done_callback(tap_tasks.discard)

        @track.on("ended")
        async def on_ended():
            await _remove_room_track(session_id, track)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        logger.info("Peer connection state changed to %s", pc.connectionState)
        if pc.connectionState in {"failed", "closed", "disconnected"}:
            await close_peer_legacy(pc, tap_tasks, session_id=session_id, speaker_id=speaker_id)

    await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=offer_type))
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}


async def close_peer(peer: PeerState) -> None:
    if peer.closed:
        return
    peer.closed = True
    if peer in session_peers[peer.session_id]:
        session_peers[peer.session_id].remove(peer)
    await _remove_speaker_tracks(peer.session_id, peer.speaker_id)
    peer_connections.discard(peer.pc)
    for task in list(peer.tap_tasks):
        task.cancel()
    await asyncio.gather(*peer.tap_tasks, return_exceptions=True)
    await peer.pc.close()


async def close_peer_legacy(
    pc: RTCPeerConnection,
    tap_tasks: set[asyncio.Task],
    *,
    session_id: str,
    speaker_id: str,
) -> None:
    peer_connections.discard(pc)
    for task in list(tap_tasks):
        task.cancel()
    await asyncio.gather(*tap_tasks, return_exceptions=True)
    await pc.close()
    await _remove_speaker_tracks(session_id, speaker_id)


async def close_all_peers() -> None:
    pcs = list(peer_connections)
    peer_connections.clear()
    await asyncio.gather(*(pc.close() for pc in pcs), return_exceptions=True)
