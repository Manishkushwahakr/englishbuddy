from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Profile(Base):
    __tablename__ = "profiles"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        primary_key=True
    )

    name = Column(String, nullable=False)
    english_level = Column(String, nullable=True)
    learning_goal = Column(String, nullable=True)

    user = relationship(
        "User",
        back_populates="profile"
    )