import jwt
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from app.models.user import UserModel
from app.schemas.user import UserCreate
from app.core.settings import settings
from app.core.security import pwd_context
import uuid

class AuthService:
    def __init__(self, db: Session):
        self.db = db

    def get_user_by_username(self, username: str) -> Optional[UserModel]:
        return self.db.query(UserModel).filter(UserModel.username == username).first()

    def create_access_token(self, username: str, role: str, user_id: str) -> str:
        to_encode = {"sub": username, "role": role, "user_id": user_id, "type": "access"}
        expire = datetime.utcnow() + timedelta(minutes=30)
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
        return encoded_jwt

    def create_refresh_token(self, username: str, role: str, user_id: str) -> str:
        to_encode = {"sub": username, "role": role, "user_id": user_id, "type": "refresh"}
        expire = datetime.utcnow() + timedelta(days=7)
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
        return encoded_jwt

    def decode_access_token(self, token: str) -> Optional[dict]:
        try:
            payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
            if payload.get("type") and payload.get("type") != "access":
                return None
            return payload
        except jwt.PyJWTError:
            return None

    def decode_refresh_token(self, token: str) -> Optional[dict]:
        try:
            payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
            if payload.get("type") != "refresh":
                return None
            return payload
        except jwt.PyJWTError:
            return None

    def create_user(self, user_in: UserCreate) -> UserModel:
        hashed = pwd_context.hash(user_in.password)
        new_user = UserModel(
            id=str(uuid.uuid4()),
            username=user_in.username,
            email=user_in.email,
            full_name=user_in.full_name,
            hashed_password=hashed,
            role="user"
        )
        self.db.add(new_user)
        self.db.commit()
        self.db.refresh(new_user)
        return new_user
