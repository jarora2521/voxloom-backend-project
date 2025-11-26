from fastapi import FastAPI, Depends, HTTPException, Header
import os
from dotenv import load_dotenv


load_dotenv()
API_KEY = os.getenv("API_KEY", "voxloom_demo_api_key")

async def require_api_key(authorization: str | None = Header(None)):
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.split(" ", 1)[1]
    if token != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")

app = FastAPI(title="VoxLoom Backend")

# import routers
from app.api.v1 import sessions, tools

app.include_router(sessions.router, prefix="/api/v1/sessions", dependencies=[Depends(require_api_key)])
app.include_router(tools.router, prefix="/api/v1/tools", dependencies=[Depends(require_api_key)])

@app.get("/")
async def root():
    return {"ok": True, "service": "voxloom-backend"}
