from sqlalchemy import Column, String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    profile = relationship(
        "Profile",
        back_populates="user",
        uselist=False
    )

    queue_entry = relationship(
        "MatchingQueue",
        back_populates="user"
    )

    conversation_participants = relationship(
        "ConversationParticipant",
        back_populates="user"
    )