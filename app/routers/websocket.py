
import asyncio
import base64
import binascii
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
from jose import jwt, JWTError

from app.config import SECRET_KEY
from app.auth.security import ALGORITHM
from app.database import SessionLocal
from app.models.conversation import Conversation
from app.models.conversation_participant import ConversationParticipant
from app.models.matching_queue import MatchingQueue
from app.services.stt import transcribe_audio

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

    if not token:
        await websocket.close(code=1008)
        return

    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        user_id = payload.get("sub")

        if not user_id:
            await websocket.close(code=1008)
            return

    except JWTError:
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

            # Speech-to-text
            if message_type == "audio_chunk":
                try:
                    encoded_audio = message.get("audio")

                    if not isinstance(encoded_audio, str) or not encoded_audio:
                        await websocket.send_json({
                            "type": "stt_error",
                            "message": "Audio data is missing"
                        })
                        continue

                    if len(encoded_audio) > 2 * 1024 * 1024:
                        await websocket.send_json({
                            "type": "stt_error",
                            "message": "Audio chunk is too large"
                        })
                        continue

                    audio_bytes = base64.b64decode(
                        encoded_audio,
                        validate=True
                    )

                    print(
                        f"STT received {len(audio_bytes)} bytes "
                        f"from user {user_id}"
                    )

                    transcript = await asyncio.to_thread(
                        transcribe_audio,
                        audio_bytes
                    )

                    print(f"STT transcript: {transcript!r}")

                    if transcript and transcript.strip():
                        transcript_message = {
                            "type": "transcript",
                            "sender_id": user_id,
                            "text": transcript.strip()
                        }

                        await manager.send_to_room(
                            conversation_id,
                            transcript_message,
                            websocket
                        )

                        if websocket.client_state == WebSocketState.CONNECTED:
                            await safe_send_json(websocket, transcript_message)
                    else:
                        if websocket.client_state == WebSocketState.CONNECTED:
                            await websocket.send_json({
                                "type": "stt_status",
                                "message": "No speech detected in this audio chunk"
                            })

                except (binascii.Error, ValueError):
                    if websocket.client_state == WebSocketState.CONNECTED:
                        await websocket.send_json({
                            "type": "stt_error",
                            "message": "Invalid audio encoding"
                        })

                except Exception as error:
                    print(f"STT error: {error}")

                    if websocket.client_state == WebSocketState.CONNECTED:
                        await websocket.send_json({
                            "type": "stt_error",
                            "message": "Could not transcribe audio"
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
