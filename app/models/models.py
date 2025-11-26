# app/models/models.py
from typing import Optional, Dict
from sqlmodel import SQLModel, Field, Column, JSON
from datetime import datetime
import uuid

def gen_uuid() -> str:
    return str(uuid.uuid4())

def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"

# Sessions table
class Session(SQLModel, table=True):
    id: str = Field(default_factory=gen_uuid, primary_key=True, index=True)
    customer_id: str
    language: str
    channel: str
    persona: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)

# Messages table
class Message(SQLModel, table=True):
    id: str = Field(default_factory=gen_uuid, primary_key=True, index=True)
    session_id: str = Field(index=True)
    direction: Optional[str] = Field(default="incoming")  # incoming / outgoing
    type: Optional[str] = None  # text / audio
    text: Optional[str] = None
    audio_path_or_b64: Optional[str] = None
    transcript: Optional[str] = None
    reply_text: Optional[str] = None
    reply_audio_path_or_b64: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)

# Model calls (ASR / LLM / TTS)
class ModelCall(SQLModel, table=True):
    id: str = Field(default_factory=gen_uuid, primary_key=True, index=True)
    message_id: Optional[str] = Field(default=None, index=True)
    model_type: Optional[str] = None  # ASR | LLM | TTS
    model_id: Optional[str] = None
    duration_ms: Optional[int] = None
    raw_response_snippet: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)

# CRM records written by MCP/tool
class CRMRecord(SQLModel, table=True):
    id: str = Field(default_factory=gen_uuid, primary_key=True, index=True)
    session_id: Optional[str] = Field(default=None, index=True)
    customer_id: Optional[str] = None
    scenario: Optional[str] = None
    record_json: Optional[Dict] = Field(sa_column=Column(JSON), default=None)
    status: Optional[str] = Field(default="pending")  # pending / done / failed
    created_at: str = Field(default_factory=now_iso)

# Tool calls log
class ToolCall(SQLModel, table=True):
    id: str = Field(default_factory=gen_uuid, primary_key=True, index=True)
    session_id: Optional[str] = Field(default=None, index=True)
    payload_json: Optional[Dict] = Field(sa_column=Column(JSON), default=None)
    status: Optional[str] = Field(default="accepted")
    created_at: str = Field(default_factory=now_iso)
