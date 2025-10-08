# executor/api/main.py
from __future__ import annotations
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.responses import HTMLResponse

# --- Cortex imports ---
from executor.core.router import route
from executor.ai.router import chat as chat_llm
from executor.utils.memory import init_db_if_needed, recall_context, remember_exchange
from executor.utils.vector_memory import store_vector, search_similar
from executor.utils.summarizer import summarize_if_needed

# ---------------------------------------------------------------------
#  FastAPI application setup
# ---------------------------------------------------------------------
app = FastAPI(title="Cortex Executor API")


@app.get("/")
def healthcheck():
    """Simple healthcheck endpoint."""
    return {"status": "ok"}


# ---------------------------------------------------------------------
#  Chat endpoint with full persistence + semantic recall
# ---------------------------------------------------------------------
class ChatBody(BaseModel):
    text: str
    boost: bool | None = False
    system: str | None = None


@app.post("/chat")
def chat(body: ChatBody):
    """
    Chat endpoint for Cortex with full persistence:
    - Loads recent context from memory.db (short-term)
    - Retrieves relevant long-term memories via vector similarity
    - Persists both user and assistant messages to both databases
    - Triggers periodic summarization
    """
    init_db_if_needed()

    # === 1️⃣ Recall recent context (short-term memory) ===
    context = recall_context(limit=6)
    context_text = "\n".join(f"{m['role']}: {m['content']}" for m in context)

    # === 2️⃣ Recall long-term memory (semantic search) ===
    memories = search_similar(body.text, top_k=5)
    memory_text = "\n".join(memories)

    # === 3️⃣ Construct full prompt ===
    if memory_text:
        full_prompt = (
            f"Relevant past memory:\n{memory_text}\n\n"
            f"Recent context:\n{context_text}\n\nUser: {body.text}"
        )
    else:
        full_prompt = f"{context_text}\nUser: {body.text}" if context_text else body.text

    # === 4️⃣ Generate response via model router ===
    reply = chat_llm(full_prompt, boost=bool(body.boost), system=body.system)

    # === 5️⃣ Persist to both short-term + vector memory ===
    remember_exchange("user", body.text)
    remember_exchange("assistant", reply)
    store_vector("user", body.text)
    store_vector("assistant", reply)

    # === 6️⃣ Trigger summarizer occasionally (non-blocking) ===
    try:
        summarize_if_needed()
    except Exception as e:
        print("[Memory] Summarizer skipped:", e)

    return {"reply": reply, "boost_used": bool(body.boost)}


# ---------------------------------------------------------------------
#  Executor task router
# ---------------------------------------------------------------------
@app.post("/execute")
def execute(user_text: str):
    """Retains existing Executor contract routing."""
    result = route(user_text)
    return {"result": result}


# ---------------------------------------------------------------------
#  In-browser UI endpoint
# ---------------------------------------------------------------------
@app.get("/ui", response_class=HTMLResponse)
def ui():
    """Interactive Cortex Chat UI with Boost mode and local memory."""
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8" />
        <title>Cortex Chat</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
            :root {
                --bg: #f7f8fa;
                --fg: #1e1e1e;
                --accent: #0066ff;
                --ai: #e8f0fe;
            }
            body {
                margin: 0; padding: 0;
                font-family: system-ui, sans-serif;
                background: var(--bg); color: var(--fg);
                display: flex; flex-direction: column;
                height: 100vh;
            }
            header {
                background: var(--accent);
                color: white; padding: 1rem;
                text-align: center; font-weight: bold;
            }
            #chat {
                flex: 1;
                overflow-y: auto;
                padding: 1rem;
                display: flex;
                flex-direction: column;
            }
            .msg { margin: .5rem 0; line-height: 1.4; }
            .user { text-align: right; }
            .user span {
                display: inline-block;
                background: var(--accent); color: white;
                padding: .5rem .8rem; border-radius: 10px 10px 0 10px;
                max-width: 80%; word-wrap: break-word;
            }
            .ai span {
                display: inline-block;
                background: var(--ai); color: var(--fg);
                padding: .5rem .8rem; border-radius: 10px 10px 10px 0;
                max-width: 80%; word-wrap: break-word;
            }
            #inputRow {
                display: flex; padding: .8rem;
                border-top: 1px solid #ddd; background: white;
            }
            #inputRow input[type=text] {
                flex: 1; padding: .6rem;
                border: 1px solid #ccc; border-radius: 6px;
                font-size: 1rem;
            }
            #inputRow button {
                margin-left: .6rem;
                padding: .6rem 1rem;
                background: var(--accent); color: white;
                border: none; border-radius: 6px;
                font-size: 1rem; cursor: pointer;
            }
            #controls {
                display: flex; align-items: center;
                justify-content: space-between;
                padding: .4rem .8rem; background: #fff; border-top: 1px solid #ddd;
                font-size: .9rem;
            }
            #boostToggle {
                transform: scale(1.2);
                margin-right: .4rem;
            }
            #typing { font-style: italic; color: #555; margin: .4rem 0; }
        </style>
    </head>
    <body>
        <header>🧠 Cortex Chat</header>
        <div id="chat"></div>
        <div id="typing" style="display:none;">Cortex is thinking…</div>
        <div id="controls">
            <label><input type="checkbox" id="boostToggle" /> Boost (GPT-5)</label>
            <button onclick="clearChat()">🧹 Clear</button>
        </div>
        <div id="inputRow">
            <input id="input" type="text" placeholder="Type your message…" onkeypress="if(event.key==='Enter')send()" />
            <button onclick="send()">Send</button>
        </div>

        <script>
        const chatEl = document.getElementById('chat');
        const typingEl = document.getElementById('typing');
        const inputEl = document.getElementById('input');
        const boostEl = document.getElementById('boostToggle');
        const history = JSON.parse(localStorage.getItem('cortex_history') || '[]');
        for (const m of history) appendMessage(m.role, m.text);

        async function send() {
            const msg = inputEl.value.trim();
            if (!msg) return;
            appendMessage('user', msg);
            inputEl.value = '';
            typingEl.style.display = 'block';
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
            div.innerHTML = `<span>${escapeHtml(text)}</span>`;
            chatEl.appendChild(div);
            chatEl.scrollTop = chatEl.scrollHeight;
            save(role, text);
        }

        function save(role, text) {
            const hist = JSON.parse(localStorage.getItem('cortex_history') || '[]');
            hist.push({ role, text });
            localStorage.setItem('cortex_history', JSON.stringify(hist.slice(-100)));
        }

        function clearChat() {
            localStorage.removeItem('cortex_history');
            chatEl.innerHTML = '';
        }

        function escapeHtml(text) {
            const map = {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'};
            return text.replace(/[&<>"']/g, m => map[m]);
        }
        </script>
    </body>
    </html>
    """