# app/api/v1/sessions.py
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field
from typing import Optional
from sqlmodel import select
from app.services.ai_pipeline import run_asr, run_tts, generate_reply
import datetime
import uuid
import os
import httpx
from dotenv import load_dotenv


load_dotenv()
API_KEY = os.getenv("API_KEY", "voxloom_demo_api_key")

# Async DB session factory
from app.db.database import AsyncSessionLocal

# Import SQLModel classes (adjusted for your layout)
try:
    from app.models.models import (
        Session as SessionModel,
        Message as MessageModel,
        CRMRecord as CRMRecordModel,
        ToolCall as ToolCallModel,
        ModelCall as ModelCallModel,
    )
except Exception:
    from app.models import (
        Session as SessionModel,
        Message as MessageModel,
        CRMRecord as CRMRecordModel,
        ToolCall as ToolCallModel,
        ModelCall as ModelCallModel,
    )


router = APIRouter()

def now_iso() -> str:
    return datetime.datetime.utcnow().isoformat() + "Z"

def gen_uuid() -> str:
    return str(uuid.uuid4())

class CreateSessionReq(BaseModel):
    customer_id: str = Field(..., example="cust_123")
    language: str = Field(..., example="en")
    channel: str = Field(..., example="phone")
    persona: Optional[str] = Field(None, example="billing_agent")

class MessageReq(BaseModel):
    type: str = Field(..., example="text")  # "text" or "audio"
    text: Optional[str] = Field(None, example="Mera bill bahut zyada aaya hai")
    audio_base64: Optional[str] = None
    mime: Optional[str] = None

@router.post("", status_code=201)
async def create_session(req: CreateSessionReq):
    """
    Persist a new session in the DB and return session_id + created_at.
    """
    session_id = gen_uuid()
    created_at = now_iso()

    session_row = SessionModel(
        id=session_id,
        customer_id=req.customer_id,
        language=req.language,
        channel=req.channel,
        persona=req.persona,
        created_at=created_at,
    )

    async with AsyncSessionLocal() as db:
        db.add(session_row)
        await db.commit()

    return {"session_id": session_id, "created_at": created_at}

@router.post("/{session_id}/messages", status_code=201)
async def post_message(session_id: str, msg: MessageReq):
    """
    Persist an incoming message to DB.
    This now calls the local ASR + rule-based LLM (generate_reply)
    and saves the reply into the message row. It also calls the
    internal MCP/tool endpoint to insert a CRM record, and logs
    ASR/LLM/TTS calls into the modelcall table.

    Important change: audio bytes are saved to disk under ./media/
    and the DB stores the path in message.audio_path_or_b64 for
    backwards compatibility.
    """
    # Validate type
    if msg.type not in ("text", "audio"):
        raise HTTPException(status_code=400, detail="type must be 'text' or 'audio'")

    message_id = gen_uuid()
    created_at = now_iso()

    # Prepare incoming text / transcript
    if msg.type == "text":
        incoming_text = msg.text or ""
        transcript = incoming_text
        audio_path_or_b64 = None
    else:
        incoming_text = None
        transcript = "<audio_received>"  # temporary until ASR runs
        audio_path_or_b64 = None

        # If we have base64 audio, save to ./media/<message_id>.wav
        if msg.audio_base64:
            try:
                import base64
                os.makedirs("media", exist_ok=True)
                audio_bytes = base64.b64decode(msg.audio_base64)
                # Determine extension using MIME if provided (basic)
                ext = ".wav"
                if msg.mime and "mp3" in msg.mime.lower():
                    ext = ".mp3"
                media_filename = f"media/{message_id}{ext}"
                with open(media_filename, "wb") as f:
                    f.write(audio_bytes)
                audio_path_or_b64 = media_filename
            except Exception as e:
                # If writing fails, still proceed but log and keep audio as None
                print("Failed to write incoming audio to disk:", str(e))
                audio_path_or_b64 = None

    # Build message row with initial values (we'll update reply fields after pipeline)
    message_row = MessageModel(
        id=message_id,
        session_id=session_id,
        direction="incoming",
        type=msg.type,
        text=incoming_text,
        audio_path_or_b64=audio_path_or_b64,
        transcript=transcript,
        reply_text=None,
        reply_audio_path_or_b64=None,
        created_at=created_at,
    )

    async with AsyncSessionLocal() as db:
        # Check session exists and load session metadata (language/persona)
        q = select(SessionModel).where(SessionModel.id == session_id)
        result = await db.execute(q)
        s = result.scalars().one_or_none()
        if s is None:
            raise HTTPException(status_code=404, detail="session not found")

        model_calls_to_save = []

        # ---- 1) ASR (if audio) ----
        if msg.type == "audio":
            asr_start = datetime.datetime.utcnow()

            # Choose ASR input: prefer saved file path if we have it, otherwise decode base64 inline
            asr_input_bytes = None
            if audio_path_or_b64:
                # we will pass the file path to run_asr (implementation can accept path)
                asr_source = audio_path_or_b64
            elif msg.audio_base64:
                # fallback: decode into bytes and pass bytes (run_asr should accept bytes or base64)
                import base64
                asr_source = base64.b64decode(msg.audio_base64)
            else:
                asr_source = b""

            transcript = await run_asr(asr_source, msg.mime or "audio/wav")
            asr_end = datetime.datetime.utcnow()
            duration_ms = int((asr_end - asr_start).total_seconds() * 1000)

            message_row.transcript = transcript

            # Log ASR model call
            asr_call = ModelCallModel(
                id=gen_uuid(),
                message_id=message_id,
                model_type="ASR",
                model_id="Systran/faster-whisper-tiny.en",
                duration_ms=duration_ms,
                raw_response_snippet=(transcript[:200] if isinstance(transcript, str) else None),
                created_at=now_iso(),
            )
            model_calls_to_save.append(asr_call)

        # ---- 2) Decide what text goes into our LLM / reply generator ----
        if msg.type == "text":
            user_text = incoming_text or ""
        else:
            user_text = transcript or ""

        # ---- 3) LLM (our generate_reply) ----
        llm_start = datetime.datetime.utcnow()
        llm_reply = await generate_reply(user_text)
        llm_end = datetime.datetime.utcnow()
        llm_duration_ms = int((llm_end - llm_start).total_seconds() * 1000)

        # Log LLM model call
        llm_call = ModelCallModel(
            id=gen_uuid(),
            message_id=message_id,
            model_type="LLM",
            model_id="rule-based-generate-reply-v1",
            duration_ms=llm_duration_ms,
            raw_response_snippet=(llm_reply[:200] if isinstance(llm_reply, str) else None),
            created_at=now_iso(),
        )
        model_calls_to_save.append(llm_call)

        # ---- 4) TTS (writes file to disk) ----
        tts_start = datetime.datetime.utcnow()
        # We'll pass the message_id so run_tts can write the reply file named with message_id
        tts_path = await run_tts(llm_reply, message_id=message_id)
        tts_end = datetime.datetime.utcnow()
        tts_duration_ms = int((tts_end - tts_start).total_seconds() * 1000)

        # Log TTS model call (even if stub / None)
        tts_snippet = None
        if isinstance(tts_path, str):
            tts_snippet = tts_path[:200]

        tts_call = ModelCallModel(
            id=gen_uuid(),
            message_id=message_id,
            model_type="TTS",
            model_id="stub-tts",
            duration_ms=tts_duration_ms,
            raw_response_snippet=tts_snippet,
            created_at=now_iso(),
        )
        model_calls_to_save.append(tts_call)

        # ---- 5) Update message with reply ----
        message_row.reply_text = llm_reply
        message_row.reply_audio_path_or_b64 = tts_path

        # Save message + model calls
        db.add(message_row)
        for mc in model_calls_to_save:
            db.add(mc)

        await db.commit()

        # ---- 6) Internal MCP / tool endpoint to create a CRM record ----
        crm_payload = {
            "session_id": session_id,
            "customer_id": getattr(s, "customer_id", None) or "cust_demo",
            "llm_response": llm_reply,
            "scenario": "billing_query",
            "crm_record": {
                "name": "Asha Sharma",
                "phone": "+91-98xxxxxxx",
                "account_id": f"acc_{session_id[:8]}",
                "query": transcript,
                "intent": "request_refund",
                "priority": "high",
            },
            "meta": {"model": "stub-llm", "confidence": 0.5},
        }

        mcp_url = "http://127.0.0.1:8000/api/v1/tools/mcp"
        headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

        # Call MCP and log status into toolcall table in the tools endpoint (we still attempt)
        try:
            async with httpx.AsyncClient() as client:
                await client.post(mcp_url, json=crm_payload, headers=headers, timeout=10.0)
        except Exception as e:
            # avoid failing the whole request — log and continue
            print("MCP call failed:", str(e))

    # Return the persisted/processed message summary
    return {
        "message_id": message_id,
        "session_id": session_id,
        "created_at": created_at,
        "incoming_text": incoming_text,
        "transcript": message_row.transcript,
        "reply_text": message_row.reply_text,
        "reply_audio_path": message_row.reply_audio_path_or_b64,
    }


@router.get("/{session_id}/conversation")
async def get_conversation(session_id: str, response: Response):
    """
    Return messages, CRM records, and tool-calls for a session.
    """
    async with AsyncSessionLocal() as db:
        # Ensure session exists
        q = select(SessionModel).where(SessionModel.id == session_id)
        r = await db.execute(q)
        session_obj = r.scalars().one_or_none()
        if session_obj is None:
            response.status_code = 404
            return {"detail": "session not found"}

        # Fetch messages
        q_msgs = select(MessageModel).where(MessageModel.session_id == session_id).order_by(MessageModel.created_at)
        r_msgs = await db.execute(q_msgs)
        messages = [m.dict() for m in r_msgs.scalars().all()]

        # Fetch CRM records
        q_crm = select(CRMRecordModel).where(CRMRecordModel.session_id == session_id).order_by(CRMRecordModel.created_at)
        r_crm = await db.execute(q_crm)
        crm_records = [c.dict() for c in r_crm.scalars().all()]

        # Fetch tool calls
        q_tools = select(ToolCallModel).where(ToolCallModel.session_id == session_id).order_by(ToolCallModel.created_at)
        r_tools = await db.execute(q_tools)
        tool_calls = [t.dict() for t in r_tools.scalars().all()]

        # Fetch model calls (ASR / LLM / TTS) belonging to messages in this session
        q_model_calls = (
            select(ModelCallModel)
            .join(MessageModel, ModelCallModel.message_id == MessageModel.id)
            .where(MessageModel.session_id == session_id)
            .order_by(ModelCallModel.created_at)
        )
        r_model_calls = await db.execute(q_model_calls)
        model_calls = [mc.dict() for mc in r_model_calls.scalars().all()]


    return {
        "session": session_obj.dict(),
        "messages": messages,
        "crm_records": crm_records,
        "tool_calls": tool_calls,
        "model_calls": model_calls,
    }
