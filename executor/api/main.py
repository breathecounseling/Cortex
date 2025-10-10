# executor/api/main.py
from __future__ import annotations
import os
from typing import List, Dict

from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.responses import HTMLResponse

# --- Cortex imports ---
from executor.core.router import route
from executor.ai.router import chat as chat_llm
from executor.utils.memory import init_db_if_needed, recall_context, remember_exchange
from executor.utils.vector_memory import store_vector, search_similar
from executor.utils.summarizer import summarize_if_needed

app = FastAPI()

class ChatBody(BaseModel):
    text: str
    boost: bool | None = False
    system: str | None = None

@app.get("/")
def healthcheck():
    return {"ok": True}

@app.post("/chat")
def chat(body: ChatBody):
    init_db_if_needed()

    # 1) recent context (short-term)
    ctx: List[Dict[str, str]] = []
    try:
        ctx = recall_context(limit=6)
    except TypeError:
        ctx = recall_context()  # older signature

    context_text = "\n".join(f"{m['role']}: {m['content']}" for m in ctx) if isinstance(ctx, list) else str(ctx)

    # 2) long-term recall (semantic) — only if API key available
    memory_text = ""
    if os.getenv("OPENAI_API_KEY"):
        try:
            memories = search_similar(body.text, top_k=5)
            memory_text = "\n".join(memories)
        except Exception:
            memory_text = ""

    # 3) call LLM (or graceful fallback)
    try:
        prompt = f"Relevant past memory:\n{memory_text}\n\nUser: {body.text}" if memory_text else body.text
        reply = chat_llm(prompt, boost=bool(body.boost), system=body.system)
    except Exception as e:
        reply = (
            "I'm running without an LLM on this server right now. "
            "Set OPENAI_API_KEY on Fly (fly secrets set OPENAI_API_KEY=...) to enable answers.\n\n"
            f"(detail: {e})"
        )

    # 4) persist exchanges; best effort
    try:
        remember_exchange("user", body.text)
        remember_exchange("assistant", reply)
    except Exception:
        pass

    # 5) store vectors + maybe summarize (only when API key available)
    if os.getenv("OPENAI_API_KEY"):
        try:
            store_vector("user", body.text)
            store_vector("assistant", reply)
            summarize_if_needed()
        except Exception:
            pass

    return {"reply": reply, "boost_used": bool(body.boost)}

@app.post("/execute")
def execute(user_text: str):
    return {"result": route(user_text)}

@app.get("/ui", response_class=HTMLResponse)
def ui():
    return HTMLResponse("""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Cortex Chat</title>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
      :root { --bg:#f7f8fa; --fg:#1e1e1e; --accent:#0066ff; --ai:#e8f0fe; }
      * { box-sizing: border-box; }
      body { margin:0; padding:0; font-family:system-ui, sans-serif; background:var(--bg); color:var(--fg); display:flex; flex-direction:column; height:100vh; }
      header { background:var(--accent); color:white; padding:1rem; text-align:center; font-weight:600; }
      #chat { flex:1; overflow-y:auto; padding:1rem; display:flex; flex-direction:column; }
      .msg { margin:.5rem 0; line-height:1.4; }
      .user { text-align:right; }
      .user span { display:inline-block; background:var(--accent); color:white; padding:.5rem .75rem; border-radius:16px; }
      .ai span { display:inline-block; background:var(--ai); color:var(--fg); padding:.5rem .75rem; border-radius:16px; }
      #composer { display:flex; gap:.5rem; padding:1rem; border-top:1px solid #e6e6e6; background:white; }
      #composer input[type=text] { flex:1; padding:.6rem .8rem; border:1px solid #d0d5dd; border-radius:8px; }
      #composer button { padding:.6rem .9rem; border:none; border-radius:8px; background:var(--accent); color:white; font-weight:600; }
      .meta { display:flex; align-items:center; gap:.75rem; padding:0 1rem .5rem; color:#555; }
      .typing { display:none; font-style:italic; color:#666; }
      .boost { display:flex; align-items:center; gap:.35rem; }
      .btn-clear { background:#eee; color:#333; }
    </style>
  </head>
  <body>
    <header>Cortex</header>
    <div id="chat"></div>
    <div class="meta">
      <label class="boost"><input id="boost" type="checkbox" /> Boost (GPT-5)</label>
      <span class="typing" id="typing">Thinking…</span>
      <button class="btn-clear" onclick="clearChat()">Clear</button>
    </div>
    <div id="composer">
      <input id="msg" type="text" placeholder="Type your message…" />
      <button onclick="send()">Send</button>
    </div>
    <script>
      const chatEl = document.getElementById('chat');
      const msgEl = document.getElementById('msg');
      const boostEl = document.getElementById('boost');
      const typingEl = document.getElementById('typing');

      (function restore() {
        const hist = JSON.parse(localStorage.getItem('cortex_history') || '[]');
        for (const {role, text} of hist) appendMessage(role, text);
      })();

      async function send() {
        const msg = msgEl.value.trim();
        if (!msg) return;
        appendMessage('user', msg);
        msgEl.value = '';
        typingEl.style.display = 'inline';
        try {
          const res = await fetch('/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: msg, boost: boostEl.checked })
          });
          const data = await res.json();
          appendMessage('ai', data.reply || '(no reply)');
        } catch (e) {
          appendMessage('ai', '⚠️ Error contacting server.');
        } finally {
          typingEl.style.display = 'none';
        }
      }

      function appendMessage(role, text) {
        const div = document.createElement('div');
        div.className = 'msg ' + role;
        div.innerHTML = '<span>' + escapeHtml(text) + '</span>';
        chatEl.appendChild(div);
        chatEl.scrollTop = chatEl.scrollHeight;
        save(role, text);
      }

      function save(role, text) {
        const hist = JSON.parse(localStorage.getItem('cortex_history') || '[]');
        hist.push({ role, text });
        localStorage.setItem('cortex_history', JSON.stringify(hist).slice(-5000));
      }

      function clearChat() {
        localStorage.removeItem('cortex_history');
        chatEl.innerHTML = '';
      }

      function escapeHtml(text) {
        const map = {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'};
        return text.replace(/[&<>\"']/g, m => map[m]);
      }
    </script>
  </body>
</html>""")