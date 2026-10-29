import logging
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import DateTime, Text, bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal


logger = logging.getLogger(__name__)


def transcript_chunk_id(
    conversation_id: str,
    speaker_id: str,
    stream_id: str,
    sequence: int,
) -> UUID:
    identity = (
        f"improbuddy:conversation-transcript:{conversation_id}:"
        f"{speaker_id}:{stream_id}:{sequence}"
    )
    return uuid5(NAMESPACE_URL, identity)


def persist_transcript_chunk(
    conversation_id: str,
    speaker_id: str,
    stream_id: str,
    sequence: int,
    transcript_text: str,
    start_time: datetime,
    end_time: datetime,
) -> bool:
    if not transcript_text:
        return False

    conversation_uuid = UUID(conversation_id)
    speaker_uuid = UUID(speaker_id)
    chunk_uuid = transcript_chunk_id(
        str(conversation_uuid),
        str(speaker_uuid),
        stream_id,
        sequence,
    )

    db = SessionLocal()
    try:
        db.execute(
            text(
                """
                INSERT INTO public.conversation_transcripts (
                    id,
                    conversation_id,
                    speaker_id,
                    transcript_text,
                    start_time,
                    end_time
                )
                VALUES (
                    :id,
                    :conversation_id,
                    :speaker_id,
                    :transcript_text,
                    :start_time,
                    :end_time
                )
                ON CONFLICT (id) DO NOTHING
                """
            ).bindparams(
                bindparam("id", type_=PostgreSQLUUID(as_uuid=True)),
                bindparam(
                    "conversation_id",
                    type_=PostgreSQLUUID(as_uuid=True),
                ),
                bindparam("speaker_id", type_=PostgreSQLUUID(as_uuid=True)),
                bindparam("transcript_text", type_=Text()),
                bindparam("start_time", type_=DateTime(timezone=True)),
                bindparam("end_time", type_=DateTime(timezone=True)),
            ),
            {
                "id": chunk_uuid,
                "conversation_id": conversation_uuid,
                "speaker_id": speaker_uuid,
                "transcript_text": transcript_text,
                "start_time": start_time,
                "end_time": end_time,
            },
        )
        db.commit()
        return True
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error(
            "Transcript persistence failed for conversation=%s "
            "speaker=%s sequence=%s error_type=%s",
            conversation_uuid,
            speaker_uuid,
            sequence,
            type(exc).__name__,
        )
        raise
    finally:
        db.close()
