from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.profile import Profile
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.schemas.profile import ProfileResponse, ProfileUpdate


router = APIRouter(
    prefix="/profile",
    tags=["Profile"]
)


@router.get(
    "",
    response_model=ProfileResponse
)
def get_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == current_user.id)
        .first()
    )

    if not profile:
        raise HTTPException(
            status_code=404,
            detail="Profile not found"
        )

    return ProfileResponse(
        user_id=str(profile.user_id),
        name=profile.name,
        english_level=profile.english_level,
        learning_goal=profile.learning_goal
    )


@router.put(
    "",
    response_model=ProfileResponse
)
def update_profile(
    data: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == current_user.id)
        .first()
    )

    if not profile:
        raise HTTPException(
            status_code=404,
            detail="Profile not found"
        )

    profile.name = data.name
    profile.english_level = data.english_level
    profile.learning_goal = data.learning_goal

    db.commit()
    db.refresh(profile)

    return ProfileResponse(
        user_id=str(profile.user_id),
        name=profile.name,
        english_level=profile.english_level,
        learning_goal=profile.learning_goal
    )