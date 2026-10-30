import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError
from starlette.websockets import WebSocketState

from app.routers import matching, websocket
from app.schemas.matching import EndConversationRequest
from app.services.conversation_lifecycle import end_conversation


class ConversationLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.conversation_id = uuid4()
        self.first_user_id = uuid4()
        self.second_user_id = uuid4()

    def make_db(self, status="matched", user_ids=None):
        conversation = SimpleNamespace(
            id=self.conversation_id,
            status=status,
            ended_at=None,
        )
        conversation_query = MagicMock()
        conversation_query.filter.return_value = conversation_query
        conversation_query.with_for_update.return_value = conversation_query
        conversation_query.first.return_value = conversation

        participant_query = MagicMock()
        participant_query.filter.return_value = participant_query
        participant_query.all.return_value = [
            (user_id,)
            for user_id in (
                user_ids
                if user_ids is not None
                else (self.first_user_id, self.second_user_id)
            )
        ]

        queue_query = MagicMock()
        queue_query.filter.return_value = queue_query
        db = MagicMock()
        db.query.side_effect = [
            conversation_query,
            participant_query,
            queue_query,
        ]
        return db, conversation, queue_query

    def test_end_is_transactional_and_idempotent(self):
        db, conversation, queue_query = self.make_db()
        with patch(
            "app.services.conversation_lifecycle.clear_conversation_transcript"
        ) as clear_transcript:
            result = end_conversation(
                db,
                self.conversation_id,
                self.first_user_id,
            )

        self.assertEqual(result[0], "ended")
        self.assertEqual(
            result[1],
            {self.first_user_id, self.second_user_id},
        )
        self.assertTrue(result[2])
        self.assertEqual(conversation.status, "ended")
        self.assertIsNotNone(conversation.ended_at)
        db.commit.assert_called_once()
        db.rollback.assert_not_called()
        queue_query.filter.return_value.update.assert_called_once_with(
            {"status": "ended"},
            synchronize_session=False,
        )
        clear_transcript.assert_called_once_with(str(self.conversation_id))

        db, conversation, _ = self.make_db(status="ended")
        previous_end_time = object()
        conversation.ended_at = previous_end_time
        result = end_conversation(
            db,
            self.conversation_id,
            self.second_user_id,
        )
        self.assertEqual(result[0], "ended")
        self.assertFalse(result[2])
        self.assertIs(conversation.ended_at, previous_end_time)
        db.commit.assert_called_once()

    def test_nonparticipant_cannot_end_conversation(self):
        db, conversation, _ = self.make_db(
            user_ids=(self.first_user_id,)
        )
        result = end_conversation(
            db,
            self.conversation_id,
            self.second_user_id,
        )
        self.assertEqual(result[0], "forbidden")
        self.assertEqual(conversation.status, "matched")
        db.commit.assert_not_called()

    def test_database_failure_rolls_back(self):
        db, _, _ = self.make_db()
        db.commit.side_effect = SQLAlchemyError("write failed")
        with self.assertRaises(SQLAlchemyError):
            end_conversation(
                db,
                self.conversation_id,
                self.first_user_id,
            )
        db.rollback.assert_called_once()


class WebSocketDisconnectTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        websocket.manager.rooms.clear()
        self.manager_patch = patch.object(
            websocket,
            "manager",
            websocket.ConnectionManager(),
        )
        self.manager_patch.start()
        self.addCleanup(self.manager_patch.stop)

    async def test_disconnect_grace_notifies_reconnect_then_call_end(self):
        conversation_id = str(uuid4())
        disconnected_user = str(uuid4())
        other_user = str(uuid4())
        peer_socket = SimpleNamespace(
            client_state=WebSocketState.CONNECTED,
            send_json=AsyncMock(),
        )
        websocket.manager.rooms[conversation_id] = [
            {"websocket": peer_socket, "user_id": other_user}
        ]

        with (
            patch.object(websocket, "DISCONNECT_GRACE_SECONDS", 0.01),
            patch.object(websocket, "mark_conversation_ended", return_value=True),
        ):
            await websocket.schedule_disconnect_grace(
                conversation_id,
                disconnected_user,
            )
            task = websocket.pending_disconnects[
                (conversation_id, disconnected_user)
            ]
            await task

        messages = [call.args[0] for call in peer_socket.send_json.call_args_list]
        self.assertEqual(
            [message["type"] for message in messages],
            ["peer_reconnecting", "call_ended"],
        )
        self.assertEqual(messages[-1]["conversation_id"], conversation_id)
        self.assertEqual(
            messages[-1]["reason"],
            "connection_lost",
        )
        self.assertNotIn(
            (conversation_id, disconnected_user),
            websocket.pending_disconnects,
        )

    async def test_call_event_is_sent_only_to_other_participants(self):
        conversation_id = str(uuid4())
        first_user_id = str(uuid4())
        second_user_id = str(uuid4())
        sender_socket = SimpleNamespace(
            client_state=WebSocketState.CONNECTED,
            send_json=AsyncMock(),
        )
        recipient_socket = SimpleNamespace(
            client_state=WebSocketState.CONNECTED,
            send_json=AsyncMock(),
        )
        websocket.manager.rooms[conversation_id] = [
            {"websocket": sender_socket, "user_id": first_user_id},
            {"websocket": recipient_socket, "user_id": second_user_id},
        ]

        await websocket.broadcast_call_event(
            conversation_id,
            exclude_user_id=first_user_id,
            message={"type": "call_ended", "conversation_id": conversation_id},
        )

        sender_socket.send_json.assert_not_awaited()
        recipient_socket.send_json.assert_awaited_once_with(
            {"type": "call_ended", "conversation_id": conversation_id}
        )

    async def test_http_end_broadcasts_only_when_it_ends_the_conversation(self):
        conversation_id = uuid4()
        user_id = uuid4()
        request = EndConversationRequest(conversation_id=conversation_id)
        db = MagicMock()
        current_user = SimpleNamespace(id=user_id)

        with (
            patch.object(
                matching,
                "end_conversation_state",
                side_effect=[
                    ("ended", {user_id}, False),
                    ("ended", {user_id}, True),
                ],
            ),
            patch.object(matching, "broadcast_call_event", new_callable=AsyncMock) as broadcast,
        ):
            await matching.end_conversation(request, current_user, db)
            broadcast.assert_not_awaited()

            await matching.end_conversation(request, current_user, db)

        broadcast.assert_awaited_once()

    async def test_reconnected_participant_cancels_pending_end(self):
        conversation_id = str(uuid4())
        user_id = str(uuid4())
        task = asyncio.create_task(asyncio.sleep(30))
        websocket.pending_disconnects[(conversation_id, user_id)] = task

        cancelled = websocket.cancel_pending_disconnect(conversation_id, user_id)
        with self.assertRaises(asyncio.CancelledError):
            await task

        self.assertTrue(cancelled)
        self.assertNotIn((conversation_id, user_id), websocket.pending_disconnects)

    async def test_explicit_hangup_ends_only_its_authenticated_conversation(self):
        conversation_id = str(uuid4())
        user_id = str(uuid4())
        fake_socket = SimpleNamespace(
            query_params={"token": "valid-token"},
            client_state=WebSocketState.CONNECTED,
            application_state=WebSocketState.CONNECTED,
            accept=AsyncMock(),
            send_json=AsyncMock(),
            receive_json=AsyncMock(return_value={"type": "hangup"}),
            close=AsyncMock(),
        )

        with (
            patch(
                "app.routers.websocket.authorized_conversation_user",
                return_value=user_id,
            ),
            patch(
                "app.routers.websocket.mark_conversation_ended",
                return_value=True,
            ) as mark_ended,
        ):
            await websocket.conversation_websocket(
                fake_socket,
                conversation_id,
            )

        mark_ended.assert_called_once_with(conversation_id, user_id)
        fake_socket.close.assert_awaited_once_with(
            code=1000,
            reason="Call ended",
        )
        self.assertEqual(websocket.manager.rooms, {})
        self.assertEqual(websocket.pending_disconnects, {})


if __name__ == "__main__":
    unittest.main()
