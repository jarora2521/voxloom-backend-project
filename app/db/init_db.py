# app/db/init_db.py
import asyncio
from sqlmodel import SQLModel
from sqlmodel import SQLModel
from typing import List
import os

# Import the engine and models
from app.db.database import engine
# import models so SQLModel metadata knows about them
# Adjust the import path if you put models in app/models/models.py
try:
    from app.models.models import Session, Message, ModelCall, CRMRecord, ToolCall
except Exception:
    # fallback if you kept models at app/models.py
    from app.models import Session, Message, ModelCall, CRMRecord, ToolCall

async def init_db() -> None:
    """Create database tables asynchronously."""
    print("Creating database tables...")
    async with engine.begin() as conn:
        # This will create tables for all SQLModel subclasses that were imported
        await conn.run_sync(SQLModel.metadata.create_all)
    print("Done — tables created.")

if __name__ == "__main__":
    asyncio.run(init_db())
