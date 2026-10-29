import json
import re
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.llm import (
    TranscriptAnalysisRequest,
    analyze_transcript,
    get_conversation_transcript,
)


class TranscriptAnalysisPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.conversation_id = uuid4()
        self.current_user = SimpleNamespace(id=uuid4())
        self.db = MagicMock()
        (
            self.db.query.return_value
            .filter.return_value
            .first.return_value
        ) = object()

    @staticmethod
    def analysis_json(summary):
        return json.dumps(
            {
                "overall_summary": summary,
                "grammar_mistakes": [],
                "repeated_words": [],
                "areas_of_improvement": [],
                "speaker_feedback": [],
            }
        )

    def test_analysis_is_saved_and_repeated_call_updates_by_conversation(self):
        request = TranscriptAnalysisRequest(
            conversation_id=self.conversation_id,
            transcript="Speaker A: Hello, how are you?",
        )
        with patch(
            "app.llm.generate_with_retry",
            side_effect=[
                self.analysis_json("First analysis"),
                self.analysis_json("Updated analysis"),
            ],
        ):
            first = analyze_transcript(request, self.current_user, self.db)
            second = analyze_transcript(request, self.current_user, self.db)

        self.assertEqual(first.overall_summary, "First analysis")
        self.assertEqual(second.overall_summary, "Updated analysis")
        self.assertEqual(self.db.execute.call_count, 2)
        self.assertEqual(self.db.commit.call_count, 2)

        sql, params = self.db.execute.call_args_list[0].args
        normalized_sql = re.sub(r"\s+", " ", str(sql)).lower()
        self.assertIn(
            "insert into public.conversation_analysis",
            normalized_sql,
        )
        self.assertIn("on conflict (conversation_id)", normalized_sql)
        self.assertIn(
            "analysis_result = excluded.analysis_result",
            normalized_sql,
        )
        self.assertIn("model_name = excluded.model_name", normalized_sql)
        self.assertIn("status = excluded.status", normalized_sql)
        self.assertIn("'completed'", normalized_sql)
        self.assertIn("updated_at = now()", normalized_sql)
        self.assertEqual(params["conversation_id"], self.conversation_id)
        self.assertEqual(
            params["analysis_result"]["overall_summary"],
            "First analysis",
        )
        self.assertEqual(params["model_name"], "gemini-3.5-flash")

        _, updated_params = self.db.execute.call_args_list[1].args
        self.assertEqual(updated_params["conversation_id"], self.conversation_id)
        self.assertEqual(
            updated_params["analysis_result"]["overall_summary"],
            "Updated analysis",
        )
        self.assertEqual(updated_params["model_name"], "gemini-3.5-flash")

    def test_non_participant_is_rejected_before_gemini_or_persistence(self):
        (
            self.db.query.return_value
            .filter.return_value
            .first.return_value
        ) = None
        request = TranscriptAnalysisRequest(
            conversation_id=self.conversation_id,
            transcript="Speaker A: Hello, how are you?",
        )

        with patch("app.llm.generate_with_retry") as generate:
            with self.assertRaises(HTTPException) as raised:
                analyze_transcript(request, self.current_user, self.db)

        self.assertEqual(raised.exception.status_code, 403)
        generate.assert_not_called()
        self.db.execute.assert_not_called()
        self.db.commit.assert_not_called()

    def test_database_failure_rolls_back_and_returns_server_error(self):
        self.db.execute.side_effect = SQLAlchemyError("write failed")
        request = TranscriptAnalysisRequest(
            conversation_id=self.conversation_id,
            transcript="Speaker A: Hello, how are you?",
        )

        with patch(
            "app.llm.generate_with_retry",
            return_value=self.analysis_json("Valid analysis"),
        ):
            with self.assertRaises(HTTPException) as raised:
                analyze_transcript(request, self.current_user, self.db)

        self.assertEqual(raised.exception.status_code, 500)
        self.db.rollback.assert_called_once()
        self.db.commit.assert_not_called()


class ConversationTranscriptAccessTests(unittest.TestCase):
    def setUp(self):
        self.conversation_id = uuid4()
        self.current_user = SimpleNamespace(id=uuid4())
        self.db = MagicMock()
        (
            self.db.query.return_value
            .filter.return_value
            .first.return_value
        ) = object()

    def test_participant_can_read_both_speakers_saved_segments(self):
        partner_id = uuid4()
        self.db.execute.return_value.mappings.return_value = [
            {
                "speaker_id": self.current_user.id,
                "transcript_text": "Hello, how are you?",
                "start_time": None,
                "end_time": None,
            },
            {
                "speaker_id": partner_id,
                "transcript_text": "Yesterday I go to market.",
                "start_time": None,
                "end_time": None,
            },
        ]

        result = get_conversation_transcript(
            self.conversation_id,
            self.current_user,
            self.db,
        )

        self.assertEqual(result.conversation_id, self.conversation_id)
        self.assertEqual(len(result.segments), 2)
        self.assertEqual(
            result.segments[0].speaker_id,
            self.current_user.id,
        )
        self.assertEqual(
            result.segments[1].speaker_id,
            partner_id,
        )
        self.assertIn(
            "ORDER BY COALESCE(start_time, created_at), created_at, id",
            str(self.db.execute.call_args.args[0]),
        )

    def test_non_participant_cannot_read_saved_segments(self):
        (
            self.db.query.return_value
            .filter.return_value
            .first.return_value
        ) = None

        with self.assertRaises(HTTPException) as raised:
            get_conversation_transcript(
                self.conversation_id,
                self.current_user,
                self.db,
            )

        self.assertEqual(raised.exception.status_code, 403)
        self.db.execute.assert_not_called()

    def test_database_failure_rolls_back_and_returns_server_error(self):
        self.db.execute.side_effect = SQLAlchemyError("read failed")

        with self.assertRaises(HTTPException) as raised:
            get_conversation_transcript(
                self.conversation_id,
                self.current_user,
                self.db,
            )

        self.assertEqual(raised.exception.status_code, 500)
        self.db.rollback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
