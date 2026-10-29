import asyncio
import base64
import json
import unittest
import wave
from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from starlette.testclient import WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.routers import transcription
from app.services.transcript_persistence import (
    persist_transcript_chunk,
    transcript_chunk_id,
)
from app.services.transcript_session import (
    clear_conversation_transcript,
    get_conversation_transcript,
)


def make_wav_chunk():
    audio = BytesIO()
    with wave.open(audio, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(b"\0\0" * 1_600)
    return audio.getvalue()


class TranscriptPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.conversation_id = uuid4()
        self.first_speaker_id = uuid4()
        self.second_speaker_id = uuid4()
        self.stream_id = str(uuid4())
        self.captured_at = "2026-10-29T12:00:00+00:00"
        self.db = MagicMock()
        self.app = FastAPI()
        self.app.include_router(transcription.router)
        self.client = TestClient(self.app)

    def tearDown(self):
        clear_conversation_transcript(str(self.conversation_id))

    def payload(self, sequence=0, stream_id=None):
        return {
            "type": "audio_chunk",
            "stream_id": stream_id or self.stream_id,
            "sequence": sequence,
            "captured_at": self.captured_at,
            "audio": base64.b64encode(make_wav_chunk()).decode("ascii"),
        }

    def connect_and_send(
        self,
        speaker_id,
        db,
        message,
        authorization_results=None,
        transcription_result="recognized words",
    ):
        auth_results = authorization_results or [
            str(speaker_id),
            str(speaker_id),
            str(speaker_id),
        ]
        with (
            patch(
                "app.routers.transcription.authorized_conversation_user",
                side_effect=auth_results,
            ),
            patch(
                "app.services.transcript_persistence.SessionLocal",
                return_value=db,
            ),
            patch(
                "app.routers.transcription.transcribe_audio",
                return_value=transcription_result,
            ),
        ):
            with self.client.websocket_connect(
                f"/ws/conversation/{self.conversation_id}/transcription?token=test"
            ) as websocket:
                ready = websocket.receive_json()
                websocket.send_json(message)
                response = websocket.receive_json()
        return ready, response

    def test_successful_chunk_persists_text_and_chunk_time_range(self):
        ready, response = self.connect_and_send(
            self.first_speaker_id,
            self.db,
            self.payload(),
        )

        self.assertEqual(ready["speaker_id"], str(self.first_speaker_id))
        self.assertEqual(response["type"], "transcription_result")
        self.assertEqual(response["text"], "recognized words")
        self.db.execute.assert_called_once()
        sql, params = self.db.execute.call_args.args
        self.assertIn(
            "INSERT INTO public.conversation_transcripts",
            str(sql),
        )
        self.assertIn("ON CONFLICT (id) DO NOTHING", str(sql))
        self.assertEqual(params["conversation_id"], self.conversation_id)
        self.assertEqual(params["speaker_id"], self.first_speaker_id)
        self.assertEqual(params["transcript_text"], "recognized words")
        self.assertNotIn("audio", params)
        self.assertNotIn("audio_bytes", params)
        self.assertEqual(
            params["start_time"],
            datetime(2026, 10, 29, 11, 59, 59, 900000, tzinfo=timezone.utc),
        )
        self.assertEqual(
            params["end_time"],
            datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc),
        )
        self.db.commit.assert_called_once()

    def test_both_participants_persist_under_their_authenticated_ids(self):
        second_db = MagicMock()
        first_result = self.connect_and_send(
            self.first_speaker_id,
            self.db,
            self.payload(sequence=0),
        )
        second_result = self.connect_and_send(
            self.second_speaker_id,
            second_db,
            self.payload(sequence=0, stream_id=str(uuid4())),
        )

        self.assertEqual(first_result[1]["type"], "transcription_result")
        self.assertEqual(second_result[1]["type"], "transcription_result")
        self.assertEqual(
            self.db.execute.call_args.args[1]["speaker_id"],
            self.first_speaker_id,
        )
        self.assertEqual(
            second_db.execute.call_args.args[1]["speaker_id"],
            self.second_speaker_id,
        )

    def test_empty_transcription_is_returned_but_not_persisted(self):
        _, response = self.connect_and_send(
            self.first_speaker_id,
            self.db,
            self.payload(),
            transcription_result="  ",
        )

        self.assertEqual(response["type"], "transcription_result")
        self.assertEqual(response["text"], "")
        self.db.execute.assert_not_called()
        self.db.commit.assert_not_called()

    def test_failed_transcription_is_not_persisted(self):
        with (
            patch(
                "app.routers.transcription.authorized_conversation_user",
                return_value=str(self.first_speaker_id),
            ),
            patch(
                "app.routers.transcription.transcribe_audio",
                side_effect=RuntimeError("test STT failure"),
            ),
        ):
            with self.client.websocket_connect(
                f"/ws/conversation/{self.conversation_id}/transcription?token=test"
            ) as websocket:
                websocket.receive_json()
                websocket.send_json(self.payload())
                response = websocket.receive_json()

        self.assertEqual(response["type"], "stt_error")
        self.db.execute.assert_not_called()

    def test_authorization_revoked_after_transcription_prevents_persistence(self):
        with (
            patch(
                "app.routers.transcription.authorized_conversation_user",
                side_effect=[
                    str(self.first_speaker_id),
                    str(self.first_speaker_id),
                    None,
                ],
            ),
            patch(
                "app.routers.transcription.transcribe_audio",
                return_value="recognized words",
            ),
            patch(
                "app.services.transcript_persistence.SessionLocal",
                return_value=self.db,
            ),
        ):
            with self.client.websocket_connect(
                f"/ws/conversation/{self.conversation_id}/transcription?token=test"
            ) as websocket:
                websocket.receive_json()
                websocket.send_json(self.payload())
                with self.assertRaises(WebSocketDisconnect):
                    websocket.receive_json()

        self.db.execute.assert_not_called()
        self.assertEqual(
            get_conversation_transcript(str(self.conversation_id)),
            [],
        )

    def test_unauthorized_or_disconnected_socket_cannot_persist(self):
        with patch(
            "app.routers.transcription.authorized_conversation_user",
            return_value=None,
        ), patch(
            "app.routers.transcription.transcribe_audio"
        ) as unauthorized_transcribe:
            with self.assertRaises(WebSocketDisconnect):
                with self.client.websocket_connect(
                    f"/ws/conversation/{self.conversation_id}/transcription?token=invalid"
                ) as websocket:
                    websocket.receive_json()
        unauthorized_transcribe.assert_not_called()

        with patch(
            "app.routers.transcription.authorized_conversation_user",
            return_value=str(self.first_speaker_id),
        ), patch("app.routers.transcription.transcribe_audio") as transcribe:
            with self.client.websocket_connect(
                f"/ws/conversation/{self.conversation_id}/transcription?token=test"
            ):
                pass

        transcribe.assert_not_called()
        self.db.execute.assert_not_called()

    def test_duplicate_retry_uses_the_same_durable_row_id(self):
        first_id = transcript_chunk_id(
            str(self.conversation_id),
            str(self.first_speaker_id),
            self.stream_id,
            4,
        )
        second_id = transcript_chunk_id(
            str(self.conversation_id),
            str(self.first_speaker_id),
            self.stream_id,
            4,
        )
        self.assertEqual(first_id, second_id)

        start_time = datetime.now(timezone.utc)
        end_time = datetime.now(timezone.utc)
        with patch(
            "app.services.transcript_persistence.SessionLocal",
            return_value=self.db,
        ):
            persist_transcript_chunk(
                str(self.conversation_id),
                str(self.first_speaker_id),
                self.stream_id,
                4,
                "retry-safe text",
                start_time,
                end_time,
            )
            persist_transcript_chunk(
                str(self.conversation_id),
                str(self.first_speaker_id),
                self.stream_id,
                4,
                "retry-safe text",
                start_time,
                end_time,
            )

        first_params = self.db.execute.call_args_list[0].args[1]
        second_params = self.db.execute.call_args_list[1].args[1]
        self.assertEqual(first_params["id"], second_params["id"])
        self.assertEqual(first_params["id"], first_id)
        self.assertEqual(self.db.execute.call_count, 2)

    def test_same_chunk_retried_after_reconnect_is_not_inserted_twice(self):
        first = self.connect_and_send(
            self.first_speaker_id,
            self.db,
            self.payload(),
        )
        retry = self.connect_and_send(
            self.first_speaker_id,
            self.db,
            self.payload(),
        )

        self.assertEqual(first[1]["type"], "transcription_result")
        self.assertEqual(retry[1]["type"], "chunk_duplicate")
        self.db.execute.assert_called_once()

    def test_socket_disconnected_before_persistence_does_not_save(self):
        class DisconnectingWebSocket:
            query_params = {"token": "test"}

            def __init__(self):
                self.state_reads = 0
                self.messages = []
                self.close_code = None

            @property
            def client_state(self):
                self.state_reads += 1
                if self.state_reads == 1:
                    return WebSocketState.CONNECTED
                return WebSocketState.DISCONNECTED

            async def accept(self):
                pass

            async def send_json(self, message):
                self.messages.append(message)

            async def receive_text(self):
                return json.dumps(self_message)

            async def close(self, code):
                self.close_code = code

        self_message = self.payload()
        websocket = DisconnectingWebSocket()

        async def run_in_thread(function, *args):
            return function(*args)

        with (
            patch(
                "app.routers.transcription.authorized_conversation_user",
                return_value=str(self.first_speaker_id),
            ),
            patch(
                "app.routers.transcription.transcribe_audio",
                return_value="recognized words",
            ),
            patch(
                "app.services.transcript_persistence.SessionLocal",
                return_value=self.db,
            ),
            patch(
                "app.routers.transcription.asyncio.to_thread",
                side_effect=run_in_thread,
            ),
        ):
            asyncio.run(
                transcription.transcription_websocket(
                    websocket,
                    str(self.conversation_id),
                )
            )

        self.db.execute.assert_not_called()
        self.assertEqual(
            get_conversation_transcript(str(self.conversation_id)),
            [],
        )

    def test_database_failure_rolls_back_and_is_reported_without_text(self):
        self.db.execute.side_effect = SQLAlchemyError("write failed")
        with (
            patch(
                "app.routers.transcription.authorized_conversation_user",
                return_value=str(self.first_speaker_id),
            ),
            patch(
                "app.services.transcript_persistence.SessionLocal",
                return_value=self.db,
            ),
            patch(
                "app.routers.transcription.transcribe_audio",
                return_value="recognized words",
            ),
        ):
            with self.client.websocket_connect(
                f"/ws/conversation/{self.conversation_id}/transcription?token=test"
            ) as websocket:
                websocket.receive_json()
                websocket.send_json(self.payload())
                response = websocket.receive_json()

        self.assertEqual(response["type"], "stt_error")
        self.assertEqual(
            response["message"],
            "Could not save this transcript chunk.",
        )
        self.assertNotIn("recognized words", json.dumps(response))
        self.db.rollback.assert_called_once()
        self.db.commit.assert_not_called()
        self.assertEqual(
            get_conversation_transcript(str(self.conversation_id)),
            [],
        )

    def test_failed_insert_can_be_retried_with_the_same_chunk_identity(self):
        self.db.execute.side_effect = [
            SQLAlchemyError("temporary write failure"),
            None,
        ]
        with (
            patch(
                "app.routers.transcription.authorized_conversation_user",
                return_value=str(self.first_speaker_id),
            ),
            patch(
                "app.services.transcript_persistence.SessionLocal",
                return_value=self.db,
            ),
            patch(
                "app.routers.transcription.transcribe_audio",
                return_value="recognized words",
            ),
        ):
            with self.client.websocket_connect(
                f"/ws/conversation/{self.conversation_id}/transcription?token=test"
            ) as websocket:
                websocket.receive_json()
                websocket.send_json(self.payload(sequence=2))
                failed = websocket.receive_json()
                websocket.send_json(self.payload(sequence=2))
                retried = websocket.receive_json()

        self.assertEqual(failed["type"], "stt_error")
        self.assertEqual(retried["type"], "transcription_result")
        self.assertEqual(self.db.execute.call_count, 2)
        self.db.rollback.assert_called_once()
        self.db.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
