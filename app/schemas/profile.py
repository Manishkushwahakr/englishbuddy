from pydantic import BaseModel, Field


class ProfileResponse(BaseModel):
    user_id: str
    name: str
    english_level: str | None
    learning_goal: str | None


class ProfileUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    english_level: str | None = None
    learning_goal: str | None = None