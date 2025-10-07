# PATCH START — Extend API with /chat while preserving / and /execute
from __future__ import annotations
from fastapi import FastAPI
from pydantic import BaseModel
from executor.core.router import route
from executor.ai.router import chat as chat_llm

app = FastAPI(title="Cortex Executor API")

@app.get("/")
def healthcheck():
    return {"status": "ok"}

class ChatBody(BaseModel):
    text: str
    boost: bool | None = False
    system: str | None = None

@app.post("/chat")
def chat(body: ChatBody):
    """
    Simple LLM passthrough:
    - Uses ROUTER_MODEL by default
    - Uses BOOST_MODEL when body.boost=True and CORTEX_BOOST_ENABLED=true
    """
    reply = chat_llm(body.text, boost=bool(body.boost), system=body.system)
    return {"reply": reply, "boost_used": bool(body.boost)}

@app.post("/execute")
def execute(user_text: str):
    """
    Keeps existing behavior for your Executor contract routing.
    """
    result = route(user_text)
    return {"result": result}
# PATCH END