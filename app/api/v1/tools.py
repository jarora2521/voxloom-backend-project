# app/api/v1/tools.py

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Any, Dict, Optional
from sqlmodel import select
import datetime
import uuid
import os

from dotenv import load_dotenv
load_dotenv()

from app.db.database import AsyncSessionLocal

# Import from models package (your project uses models.py + __init__.py)
try:
    from app.models import (
        CRMRecord as CRMRecordModel,
        ToolCall as ToolCallModel,
        Session as SessionModel,
    )
except Exception:
    # fallback direct
    from app.models.models import (
        CRMRecord as CRMRecordModel,
        ToolCall as ToolCallModel,
        Session as SessionModel,
    )

router = APIRouter()

# ----------------------------------------------------------------------
# Utils
# ----------------------------------------------------------------------
def gen_uuid() -> str:
    return str(uuid.uuid4())

def now_iso() -> str:
    return datetime.datetime.utcnow().isoformat() + "Z"


# ----------------------------------------------------------------------
# Payload Models
# ----------------------------------------------------------------------
class MCPPayload(BaseModel):
    session_id: str
    customer_id: Optional[str]
    llm_response: Optional[str]
    scenario: Optional[str]
    crm_record: Optional[Dict[str, Any]]
    meta: Optional[Dict[str, Any]] = None


# ----------------------------------------------------------------------
# MCP Handler
# ----------------------------------------------------------------------
@router.post("/mcp", status_code=201)
async def mcp_handler(payload: MCPPayload, request: Request):
    """
    Internal MCP/tool endpoint.
    Adds CRMRecord + ToolCall.
    ToolCall.status is "accepted" on success, "failed" on DB error.
    """

    # Validate scenario
    if not payload.scenario:
        raise HTTPException(status_code=400, detail="scenario is required")

    # Billing scenario required fields
    if payload.scenario == "billing_query":
        rec = payload.crm_record or {}
        missing = [f for f in ["name", "phone", "account_id", "query", "intent", "priority"] if not rec.get(f)]
        if missing:
            raise HTTPException(status_code=400, detail=f"Missing crm_record fields: {missing}")

    async with AsyncSessionLocal() as db:
        # Ensure session exists
        q = select(SessionModel).where(SessionModel.id == payload.session_id)
        r = await db.execute(q)
        session_row = r.scalars().one_or_none()

        if session_row is None:
            raise HTTPException(status_code=404, detail="session not found")

        # Create CRMRecord
        crm_row = CRMRecordModel(
            id=gen_uuid(),
            session_id=payload.session_id,
            customer_id=payload.customer_id or session_row.customer_id,
            scenario=payload.scenario,
            record_json=payload.crm_record or {},
            status="pending",
            created_at=now_iso(),
        )

        # Create ToolCall
        tool_row = ToolCallModel(
            id=gen_uuid(),
            session_id=payload.session_id,
            payload_json=payload.dict(),
            status="accepted",     # default, will change if fails
            created_at=now_iso(),
        )

        # Try writing DB
        try:
            db.add(crm_row)
            db.add(tool_row)
            await db.commit()

        except Exception as e:
            # Mark tool call as failed
            try:
                tool_row.status = "failed"
                db.add(tool_row)
                await db.commit()
            except:
                pass

            raise HTTPException(status_code=500, detail=f"DB error: {e}")

    return {
        "ok": True,
        "status": tool_row.status,
        "crm_record_id": crm_row.id,
        "tool_call_id": tool_row.id,
    }
