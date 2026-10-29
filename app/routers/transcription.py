import asyncio
import base64
import binascii
import json
import logging
import struct
import threading
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
from sqlalchemy.exc import SQLAlchemyError

from app.services.conversation_access import authorized_conversation_user
from app.services.stt import transcribe_audio
from app.services.transcript_persistence import persist_transcript_chunk
from app.services.transcript_session import (
    claim_chunk,
    discard_transcript,
    release_chunk,
    store_transcript,
)


router = APIRouter(tags=["Transcription"])
logger = logging.getLogger(__name__)

MAX_MESSAGE_CHARACTERS = 500_000
MAX_AUDIO_BYTES = 256 * 1024
MAX_AUDIO_SECONDS = 8
TRANSCRIPTION_SLOT = threading.BoundedSemaphore(1)


def validate_wav_chunk(audio: bytes):
    if (
        len(audio) < 44
        or len(audio) > MAX_AUDIO_BYTES
        or audio[:4] != b"RIFF"
        or audio[8:12] != b"WAVE"
        or audio[12:16] != b"fmt "
        or struct.unpack_from("<I", audio, 4)[0] != len(audio) - 8
        or struct.unpack_from("<I", audio, 16)[0] != 16
        or audio[36:40] != b"data"
        or struct.unpack_from("<I", audio, 40)[0] != len(audio) - 44
    ):
        return False

    format_code, channels, sample_rate, byte_rate, block_align, bits_per_sample = struct.unpack_from(
        "<HHIIHH",
        audio,
        20
    )
    sample_count = struct.unpack_from("<I", audio, 40)[0] // 2
    return (
        format_code == 1
        and channels == 1
        and sample_rate == 16_000
        and byte_rate == 32_000
        and block_align == 2
        and bits_per_sample == 16
        and len(audio) == 44 + sample_count * 2
        and 0 < sample_count <= sample_rate * MAX_AUDIO_SECONDS
    )


def transcribe_reserved(audio_buffer: bytearray):
    try:
        return transcribe_audio(audio_buffer)
    finally:
        audio_buffer[:] = b"\0" * len(audio_buffer)
        TRANSCRIPTION_SLOT.release()


async def send_json(websocket: WebSocket, message: dict):
    if websocket.client_state != WebSocketState.CONNECTED:
        return False
    try:
        await websocket.send_json(message)
        return True
    except (WebSocketDisconnect, RuntimeError):
        return False


@router.websocket("/ws/conversation/{conversation_id}/transcription")
async def transcription_websocket(websocket: WebSocket, conversation_id: str):
    token = websocket.query_params.get("token")
    user_id = await asyncio.to_thread(
        authorized_conversation_user,
        token,
        conversation_id
    )
    if not user_id:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    await send_json(websocket, {
        "type": "transcription_ready",
        "conversation_id": conversation_id,
        "speaker_id": user_id,
    })

    last_sequence_by_stream = {}
    try:
        while True:
            raw_message = await websocket.receive_text()
            if len(raw_message) > MAX_MESSAGE_CHARACTERS:
                await send_json(websocket, {
                    "type": "stt_error",
                    "message": "Audio chunk is too large."
                })
                continue

            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                await send_json(websocket, {
                    "type": "stt_error",
                    "message": "Invalid transcription message."
                })
                continue

            if not isinstance(message, dict) or message.get("type") != "audio_chunk":
                await send_json(websocket, {
                    "type": "stt_error",
                    "message": "Unsupported transcription message."
                })
                continue

            stream_id = message.get("stream_id")
            sequence = message.get("sequence")
            encoded_audio = message.get("audio")
            captured_at = message.get("captured_at")
            if (
                not isinstance(stream_id, str)
                or len(stream_id) != 36
                or not isinstance(sequence, int)
                or isinstance(sequence, bool)
                or sequence < 0
                or sequence > 2_147_483_647
                or not isinstance(encoded_audio, str)
                or not encoded_audio
                or len(encoded_audio) > ((MAX_AUDIO_BYTES + 2) // 3) * 4
                or not isinstance(captured_at, str)
                or len(captured_at) > 64
            ):
                await send_json(websocket, {
                    "type": "stt_error",
                    "message": "Invalid audio chunk metadata."
                })
                continue

            try:
                stream_id = str(UUID(stream_id))
            except ValueError:
                await send_json(websocket, {
                    "type": "stt_error",
                    "message": "Invalid audio stream identifier."
                })
                continue

            try:
                parsed_capture_time = datetime.fromisoformat(
                    captured_at.replace("Z", "+00:00")
                )
                if parsed_capture_time.tzinfo is None:
                    raise ValueError("Timestamp must include a timezone")
            except ValueError:
                await send_json(websocket, {
                    "type": "stt_error",
                    "message": "Invalid audio capture timestamp."
                })
                continue

            stream_key = (user_id, stream_id)
            if sequence <= last_sequence_by_stream.get(stream_key, -1):
                await send_json(websocket, {
                    "type": "chunk_duplicate",
                    "sequence": sequence,
                })
                continue

            if not TRANSCRIPTION_SLOT.acquire(blocking=False):
                await send_json(websocket, {
                    "type": "stt_error",
                    "sequence": sequence,
                    "message": "Transcription is busy. This audio chunk was discarded."
                })
                continue

            slot_transferred = False
            audio_buffer = None
            claimed = False
            worker = None
            try:
                authorized_user_id = await asyncio.to_thread(
                    authorized_conversation_user,
                    token,
                    conversation_id
                )
                if authorized_user_id != user_id:
                    await websocket.close(code=1008)
                    return

                try:
                    decoded_audio = base64.b64decode(encoded_audio, validate=True)
                    audio_buffer = bytearray(decoded_audio)
                    del decoded_audio
                    encoded_audio = ""
                    message["audio"] = ""
                    raw_message = ""
                except (binascii.Error, ValueError):
                    await send_json(websocket, {
                        "type": "stt_error",
                        "sequence": sequence,
                        "message": "Invalid audio encoding."
                    })
                    continue

                if not validate_wav_chunk(audio_buffer):
                    await send_json(websocket, {
                        "type": "stt_error",
                        "sequence": sequence,
                        "message": "Audio must be a bounded mono 16 kHz PCM WAV chunk."
                    })
                    continue

                duration_ms = (
                    struct.unpack_from("<I", audio_buffer, 40)[0]
                    // 2
                    * 1000
                    // 16_000
                )
                claim_result = claim_chunk(
                    conversation_id,
                    user_id,
                    stream_id,
                    sequence
                )
                if claim_result == "duplicate":
                    last_sequence_by_stream[stream_key] = sequence
                    await send_json(websocket, {
                        "type": "chunk_duplicate",
                        "sequence": sequence,
                    })
                    continue
                if claim_result == "limit":
                    await send_json(websocket, {
                        "type": "stt_error",
                        "message": "The in-memory transcript reached its session limit."
                    })
                    await websocket.close(code=1013)
                    return
                claimed = True

                received_at = datetime.now(timezone.utc).isoformat()
                worker = asyncio.create_task(
                    asyncio.to_thread(transcribe_reserved, audio_buffer)
                )
                slot_transferred = True
                try:
                    transcript = await asyncio.shield(worker)
                except asyncio.CancelledError:
                    try:
                        await asyncio.shield(worker)
                    except Exception:
                        logger.exception("Transcription worker failed during disconnect cleanup")
                    if claimed:
                        release_chunk(
                            conversation_id,
                            user_id,
                            stream_id,
                            sequence
                        )
                        claimed = False
                    raise
                finally:
                    audio_buffer = None

                processed_at = datetime.now(timezone.utc).isoformat()

                text = transcript.strip()[:5_000]
                authorized_user_id = await asyncio.to_thread(
                    authorized_conversation_user,
                    token,
                    conversation_id
                )
                if authorized_user_id != user_id:
                    release_chunk(
                        conversation_id,
                        user_id,
                        stream_id,
                        sequence
                    )
                    claimed = False
                    await websocket.close(code=1008)
                    return

                if not text:
                    store_transcript(
                        conversation_id,
                        user_id,
                        stream_id,
                        sequence,
                        parsed_capture_time.isoformat(),
                        received_at,
                        processed_at,
                        duration_ms,
                        text,
                    )
                    release_chunk(
                        conversation_id,
                        user_id,
                        stream_id,
                        sequence,
                    )
                elif not store_transcript(
                    conversation_id,
                    user_id,
                    stream_id,
                    sequence,
                    parsed_capture_time.isoformat(),
                    received_at,
                    processed_at,
                    duration_ms,
                    text,
                ):
                    release_chunk(
                        conversation_id,
                        user_id,
                        stream_id,
                        sequence
                    )
                    await send_json(websocket, {
                        "type": "stt_error",
                        "sequence": sequence,
                        "message": "The in-memory transcript reached its session limit."
                    })
                    await websocket.close(code=1013)
                    return

                if text:
                    if websocket.client_state != WebSocketState.CONNECTED:
                        discard_transcript(
                            conversation_id,
                            user_id,
                            stream_id,
                            sequence,
                        )
                        claimed = False
                        return

                    try:
                        await asyncio.to_thread(
                            persist_transcript_chunk,
                            conversation_id,
                            user_id,
                            stream_id,
                            sequence,
                            text,
                            parsed_capture_time
                            - timedelta(milliseconds=duration_ms),
                            parsed_capture_time,
                        )
                    except SQLAlchemyError:
                        discard_transcript(
                            conversation_id,
                            user_id,
                            stream_id,
                            sequence,
                        )
                        claimed = False
                        await send_json(websocket, {
                            "type": "stt_error",
                            "sequence": sequence,
                            "message": "Could not save this transcript chunk.",
                        })
                        continue

                last_sequence_by_stream[stream_key] = sequence
                await send_json(websocket, {
                    "type": "transcription_result",
                    "conversation_id": conversation_id,
                    "speaker_id": user_id,
                    "sequence": sequence,
                    "captured_at": parsed_capture_time.isoformat(),
                    "received_at": received_at,
                    "processed_at": processed_at,
                    "duration_ms": duration_ms,
                    "text": text,
                })
                claimed = False
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Transcription failed for conversation %s, speaker %s, sequence %s",
                    conversation_id,
                    user_id,
                    sequence
                )
                if claimed:
                    release_chunk(
                        conversation_id,
                        user_id,
                        stream_id,
                        sequence
                    )
                await send_json(websocket, {
                    "type": "stt_error",
                    "sequence": sequence,
                    "message": "Could not transcribe this audio chunk."
                })
            finally:
                if audio_buffer is not None:
                    audio_buffer[:] = b"\0" * len(audio_buffer)
                if not slot_transferred:
                    TRANSCRIPTION_SLOT.release()
                encoded_audio = ""
                if isinstance(message, dict):
                    message["audio"] = ""
                raw_message = ""
    except WebSocketDisconnect:
        return
