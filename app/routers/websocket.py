
import asyncio
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.database import SessionLocal
from app.models.conversation import Conversation
from app.models.conversation_participant import ConversationParticipant
from app.models.matching_queue import MatchingQueue
from app.services.conversation_access import authorized_conversation_user
from app.services.transcript_session import clear_conversation_transcript

router = APIRouter(tags=["WebSocket"])


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
        self.rooms = {}

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


def mark_conversation_ended(conversation_id: str, user_id: str):
    db = SessionLocal()
    try:
        conversation = (
            db.query(Conversation)
            .filter(
                Conversation.id == UUID(conversation_id),
                Conversation.status == "matched"
            )
            .with_for_update()
            .first()
        )
        if conversation is None:
            return

        participants = (
            db.query(ConversationParticipant.user_id)
            .filter(
                ConversationParticipant.conversation_id == conversation.id
            )
            .all()
        )
        participant_ids = {row[0] for row in participants}
        if UUID(user_id) not in participant_ids:
            return

        conversation.status = "ended"
        conversation.ended_at = datetime.now(timezone.utc)
        db.query(MatchingQueue).filter(
            MatchingQueue.user_id.in_(participant_ids),
            MatchingQueue.status == "matched"
        ).update({"status": "ended"}, synchronize_session=False)
        db.commit()
        clear_conversation_transcript(str(conversation.id))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


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

    await manager.connect(
        websocket,
        conversation_id,
        user_id
    )

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

            if message_type == "audio_chunk":
                await safe_send_json(websocket, {
                    "type": "stt_error",
                    "message": "Send audio chunks on the separate transcription connection."
                })
                continue

            # Existing WebRTC signaling
            message["sender_id"] = user_id

            await manager.send_to_room(
                conversation_id,
                message,
                websocket
            )

    except WebSocketDisconnect:
        print(
            f"User {user_id} disconnected from "
            f"conversation {conversation_id}"
        )

    except Exception as error:
        print(f"WebSocket error for user {user_id}: {error}")

    finally:
        manager.disconnect(websocket, conversation_id)
        try:
            await asyncio.to_thread(
                mark_conversation_ended,
                conversation_id,
                user_id
            )
        except Exception as error:
            print(
                f"Could not end conversation {conversation_id} after "
                f"user {user_id} disconnected: {error}"
            )

        # Notify remaining users without sending to dead sockets.
        await manager.send_to_room(
            conversation_id,
            {
                "type": "user_disconnected",
                "user_id": user_id,
                "message": "The other user has disconnected"
            },
            websocket
        )
