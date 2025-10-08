# executor/api/main.py
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
    Chat endpoint for Cortex:
    - Uses ROUTER_MODEL by default.
    - Uses BOOST_MODEL if boost=True and Boost Mode enabled.
    """
    reply = chat_llm(body.text, boost=bool(body.boost), system=body.system)
    return {"reply": reply, "boost_used": bool(body.boost)}


@app.post("/execute")
def execute(user_text: str):
    """
    Retains existing Executor contract routing.
    """
    result = route(user_text)
    return {"result": result}

# PATCH START — add in-browser chat UI with boost + memory
from fastapi.responses import HTMLResponse

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

        // Load history
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
                    body: JSON.stringify({
                        text: msg,
                        boost: boostEl.checked
                    })
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
            hist.push({role, text});
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
# PATCH END