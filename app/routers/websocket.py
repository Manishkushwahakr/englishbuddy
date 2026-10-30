
import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.database import SessionLocal
from app.services.conversation_access import authorized_conversation_user
from app.services.conversation_lifecycle import end_conversation

router = APIRouter(tags=["WebSocket"])
logger = logging.getLogger(__name__)
DISCONNECT_GRACE_SECONDS = 15
pending_disconnects: dict[tuple[str, str], asyncio.Task] = {}


async def safe_send_json(websocket: WebSocket, message: dict):
    if websocket.client_state != WebSocketState.CONNECTED:
        return False

    try:
        await websocket.send_json(message)
        return True
    except (WebSocketDisconnect, RuntimeError):
        return False



class ConnectionManager:
    def __init__(self):
        self.rooms: dict[str, list[dict]] = {}

    async def connect(
        self,
        websocket: WebSocket,
        conversation_id: str,
        user_id: str
    ):
        await websocket.accept()

        if conversation_id not in self.rooms:
            self.rooms[conversation_id] = []

        self.rooms[conversation_id].append({
            "websocket": websocket,
            "user_id": user_id
        })

    def disconnect(
        self,
        websocket: WebSocket,
        conversation_id: str
    ):
        if conversation_id not in self.rooms:
            return

        self.rooms[conversation_id] = [
            connection
            for connection in self.rooms[conversation_id]
            if connection["websocket"] is not websocket
        ]

        if not self.rooms[conversation_id]:
            del self.rooms[conversation_id]

    def has_user_connection(self, conversation_id: str, user_id: str) -> bool:
        return any(
            connection["user_id"] == user_id
            and connection["websocket"].client_state == WebSocketState.CONNECTED
            for connection in self.rooms.get(conversation_id, [])
        )

    async def send_to_room(
        self,
        conversation_id: str,
        message: dict,
        sender: WebSocket
    ):
        connections = self.rooms.get(conversation_id, [])

        for connection in connections.copy():
            target = connection["websocket"]

            if target is sender:
                continue

            if target.client_state != WebSocketState.CONNECTED:
                self.disconnect(target, conversation_id)
                continue

            try:
                await target.send_json(message)
            except (WebSocketDisconnect, RuntimeError):
                self.disconnect(target, conversation_id)


manager = ConnectionManager()


async def broadcast_call_event(
    conversation_id: str,
    exclude_user_id: str,
    message: dict,
):
    for connection in manager.rooms.get(conversation_id, []).copy():
        target = connection["websocket"]
        if connection["user_id"] == exclude_user_id:
            continue
        if target.client_state != WebSocketState.CONNECTED:
            manager.disconnect(target, conversation_id)
            continue
        try:
            await target.send_json(message)
        except (WebSocketDisconnect, RuntimeError):
            manager.disconnect(target, conversation_id)


def mark_conversation_ended(conversation_id: str, user_id: str) -> bool:
    db = SessionLocal()
    try:
        state, _, changed = end_conversation(db, UUID(conversation_id), UUID(user_id))
        return state == "ended" and changed
    finally:
        db.close()


def cancel_pending_disconnect(conversation_id: str, user_id: str) -> bool:
    key = (conversation_id, user_id)
    task = pending_disconnects.pop(key, None)
    if task is None:
        return False
    task.cancel()
    return True


async def end_after_disconnect_grace(conversation_id: str, user_id: str):
    key = (conversation_id, user_id)
    try:
        await asyncio.sleep(DISCONNECT_GRACE_SECONDS)
        if manager.has_user_connection(conversation_id, user_id):
            return

        ended = await asyncio.to_thread(
            mark_conversation_ended,
            conversation_id,
            user_id,
        )
        if ended:
            await broadcast_call_event(
                conversation_id,
                exclude_user_id=user_id,
                message={
                    "type": "call_ended",
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "reason": "connection_lost",
                    "message": "The other participant could not reconnect.",
                },
            )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(
            "Could not end conversation %s after participant %s disconnected",
            conversation_id,
            user_id,
        )
        await broadcast_call_event(
            conversation_id,
            exclude_user_id=user_id,
            message={
                "type": "call_end_failed",
                "conversation_id": conversation_id,
                "user_id": user_id,
                "message": "The server could not confirm that the call ended.",
            },
        )
    finally:
        if pending_disconnects.get(key) is asyncio.current_task():
            pending_disconnects.pop(key, None)


async def schedule_disconnect_grace(conversation_id: str, user_id: str):
    key = (conversation_id, user_id)
    existing = pending_disconnects.get(key)
    if existing is None or existing.done():
        pending_disconnects[key] = asyncio.create_task(
            end_after_disconnect_grace(conversation_id, user_id)
        )
    await broadcast_call_event(
        conversation_id,
        exclude_user_id=user_id,
        message={
            "type": "peer_reconnecting",
            "conversation_id": conversation_id,
            "user_id": user_id,
            "grace_seconds": DISCONNECT_GRACE_SECONDS,
            "message": "The other participant lost signaling. Waiting for them to reconnect.",
        },
    )

@router.websocket("/ws/conversation/{conversation_id}")
async def conversation_websocket(
    websocket: WebSocket,
    conversation_id: str
):
    token = websocket.query_params.get("token")
    user_id = await asyncio.to_thread(
        authorized_conversation_user,
        token,
        conversation_id
    )
    if not user_id:
        await websocket.close(code=1008)
        return

    reconnected = cancel_pending_disconnect(conversation_id, user_id)
    await manager.connect(
        websocket,
        conversation_id,
        user_id
    )
    if reconnected:
        await broadcast_call_event(
            conversation_id,
            exclude_user_id=user_id,
            message={
                "type": "peer_reconnected",
                "conversation_id": conversation_id,
                "user_id": user_id,
                "message": "The other participant reconnected.",
            },
        )

    explicitly_ended = False
    try:
        await websocket.send_json({
            "type": "connected",
            "conversation_id": conversation_id,
            "user_id": user_id,
            "message": "Joined conversation room"
        })

        while True:
            message = await websocket.receive_json()
            message_type = message.get("type")

            if message_type == "hangup":
                ended = await asyncio.to_thread(
                    mark_conversation_ended,
                    conversation_id,
                    user_id,
                )
                explicitly_ended = True
                if ended:
                    await broadcast_call_event(
                        conversation_id,
                        exclude_user_id=user_id,
                        message={
                            "type": "call_ended",
                            "conversation_id": conversation_id,
                            "user_id": user_id,
                            "reason": "participant_ended",
                            "message": "The other participant ended the call.",
                        },
                    )
                break

            if message_type == "audio_chunk":
                await safe_send_json(websocket, {
                    "type": "stt_error",
                    "message": "Send audio chunks on the separate transcription connection."
                })
                continue

            if message_type in {
                "call_ended",
                "call_end_failed",
                "peer_reconnecting",
                "peer_reconnected",
                "user_disconnected",
            }:
                logger.warning(
                    "Ignored client-sent server event %s for conversation %s",
                    message_type,
                    conversation_id,
                )
                continue

            # Existing WebRTC signaling
            message["sender_id"] = user_id

            await manager.send_to_room(
                conversation_id,
                message,
                websocket
            )

    except WebSocketDisconnect:
        logger.info(
            "Participant %s disconnected from conversation %s",
            user_id,
            conversation_id,
        )

    except Exception:
        logger.exception(
            "WebSocket failure for participant %s in conversation %s",
            user_id,
            conversation_id,
        )

    finally:
        manager.disconnect(websocket, conversation_id)
        if (
            explicitly_ended
            and websocket.application_state == WebSocketState.CONNECTED
        ):
            try:
                await websocket.close(code=1000, reason="Call ended")
            except (WebSocketDisconnect, RuntimeError):
                logger.debug(
                    "WebSocket already closed after hangup for conversation %s",
                    conversation_id,
                )
        if not explicitly_ended and not manager.has_user_connection(
            conversation_id,
            user_id,
        ):
            await schedule_disconnect_grace(conversation_id, user_id)
