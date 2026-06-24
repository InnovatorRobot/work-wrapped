"""SQLAlchemy ORM models.

Tables:
  - users          : local accounts (email + PBKDF2 password hash)
  - service_cache  : cached, fetched content per user + time range so we don't
                     re-query Gerrit / Jira / Confluence / Slack on every load.
"""

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(String(32), primary_key=True)  # secrets.token_hex(8)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(120), default="")
    password_salt = Column(String(64), nullable=False)
    password_hash = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name or "",
            "password_salt": self.password_salt,
            "password_hash": self.password_hash,
            "created_at": (
                self.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if self.created_at else None
            ),
        }


class ServiceCache(Base):
    """Cached content bundle (Gerrit/Jira/Confluence/Slack) for one user + time range."""

    __tablename__ = "service_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(32), index=True, nullable=False)
    cache_key = Column(String(64), nullable=False)  # e.g. the number of months
    payload = Column(Text, nullable=False)  # JSON-encoded raw service data
    fetched_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "cache_key", name="uq_service_cache"),)


class Credential(Base):
    """Per-service credentials, encrypted at rest (one row per user + service)."""

    __tablename__ = "credentials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(32), index=True, nullable=False)
    service = Column(String(32), nullable=False)  # gerrit | jira | confluence | slack
    payload = Column(Text, nullable=False)  # Fernet-encrypted JSON of the fields
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "service", name="uq_credentials"),)
