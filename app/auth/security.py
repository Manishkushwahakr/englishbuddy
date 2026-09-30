from passlib.context import CryptContext
from jose import jwt
from datetime import datetime, timedelta

from app.config import SECRET_KEY


pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(
    plain_password: str,
    hashed_password: str
) -> bool:
    return pwd_context.verify(
        plain_password,
        hashed_password
    )


def create_access_token(
    user_id: str,
    expires_minutes: int = 60
) -> str:

    expire = datetime.utcnow() + timedelta(
        minutes=expires_minutes
    )

    payload = {
        "sub": user_id,
        "exp": expire
    }

    return jwt.encode(
        payload,
        SECRET_KEY,
        algorithm=ALGORITHM
    )