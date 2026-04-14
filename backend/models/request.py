# Pydantic models for incoming requests
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from backend.config import AppMode


class QueryRequest(BaseModel):
    """Payload for POST /query"""

    question   : str = Field(
        ...,
        min_length = 3,
        max_length = 500,
        description = "Natural language question from the user."
    )
    session_id : str = Field(
        ...,
        description = "Client-generated session ID to track conversation history."
    )
    mode       : AppMode = Field(
        default     = AppMode.DEMO,
        description = "demo | custom"
    )

    @field_validator("question")
    @classmethod
    def strip_and_check(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Question cannot be empty or whitespace.")
        return v


class CredentialsInput(BaseModel):
    """
    Payload for custom mode — user supplies their own DB + API key.
    Sent once at session start; never stored permanently.
    """

    database_url  : str = Field(
        ...,
        description = "PostgreSQL connection string: postgresql+asyncpg://user:pass@host:port/db"
    )
    gemini_api_key: str = Field(
        ...,
        min_length  = 10,
        description = "User's Gemini API key."
    )

    @field_validator("database_url")
    @classmethod
    def validate_db_url(cls, v: str) -> str:
        v = v.strip()
        if not (v.startswith("postgresql://") or v.startswith("postgresql+asyncpg://")):
            raise ValueError(
                "DATABASE_URL must start with postgresql:// or postgresql+asyncpg://"
            )
        return v


class SchemaRefreshRequest(BaseModel):
    """Payload for POST /schema/refresh in custom mode."""

    database_url: Optional[str] = Field(
        default     = None,
        description = "If provided, refreshes schema for this specific DB URL."
    )