# cortex/executor/api_server.py
from __future__ import annotations
import asyncio
from typing import Dict, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from executor.audit.logger import get_logger, initialize_logging
from executor.utils.memory import init_db_if_needed
from repl import process_message  # Adjust import if needed

logger = get_logger(__name__)

# Initialize core systems
initialize_logging()
init_db_if_needed()

app = FastAPI(title="Cortex API Server")

# Allow React dev client and others to access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Cortex API server started and ready for chat connections.")

# --- REST Endpoint ---
@app.post("/api/chat")
async def chat_api(data: Dict[str, Any]):
    """
    Accepts a user message and returns REPL's response.
    """
    user_message = data.get("message", "")
    logger.info(f"REST chat message received: {user_message}")
    # Call REPL processor in a thread to avoid blocking
    reply = await asyncio.to_thread(process_message, user_message)
    return {"response": reply}

# --- WebSocket Endpoint ---
@app.websocket("/ws/chat")
async def chat_ws(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket chat connection established.")
    try:
        while True:
            msg = await websocket.receive_text()
            logger.info(f"WS received: {msg}")
            # Process the message asynchronously
            reply = await asyncio.to_thread(process_message, msg)
            await websocket.send_json({"message": reply})
    except WebSocketDisconnect:
        logger.info("WebSocket chat disconnected.")
    except Exception as e:
        logger.exception(f"Error in WebSocket chat: {e}")
        await websocket.close(code=1011)