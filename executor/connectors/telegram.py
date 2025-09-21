# executor/connectors/telegram.py
from __future__ import annotations
import os
import requests
from dotenv import load_dotenv

from executor.plugins.conversation_manager.conversation_manager import save_turn

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")  # add to .env
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")      # your user or group chat ID

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

def send_message(text: str) -> bool:
    """
    Send a text message via Telegram bot to the configured chat.
    """
    if not BOT_TOKEN or not CHAT_ID:
        print("⚠️ Telegram not configured (missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID).")
        return False

    try:
        r = requests.post(f"{API_URL}/sendMessage", json={"chat_id": CHAT_ID, "text": text})
        return r.status_code == 200
    except Exception as e:
        print(f"Telegram send error: {e}")
        return False


def get_updates(offset: int | None = None) -> list[dict]:
    """
    Fetch new messages sent to the bot.
    """
    if not BOT_TOKEN:
        return []
    try:
        params = {"timeout": 10}
        if offset:
            params["offset"] = offset
        r = requests.get(f"{API_URL}/getUpdates", params=params, timeout=20)
        if r.status_code == 200:
            return r.json().get("result", [])
    except Exception as e:
        print(f"Telegram poll error: {e}")
    return []


def process_replies(session: str = "repl") -> None:
    """
    Poll for replies and save them into conversation history.
    Use scheduler to run this periodically.
    """
    offset_file = ".executor/telegram_offset"
    last_offset = None
    if os.path.exists(offset_file):
        try:
            last_offset = int(open(offset_file).read().strip())
        except Exception:
            pass

    updates = get_updates(offset=last_offset + 1 if last_offset else None)
    for u in updates:
        update_id = u["update_id"]
        message = u.get("message") or {}
        text = message.get("text")
        from_user = message.get("from", {}).get("username", "unknown")

        if text:
            save_turn(session, "user", f"[Telegram @{from_user}]: {text}")
            print(f"📩 Telegram reply from {from_user}: {text}")

        # advance offset so we don’t reprocess
        with open(offset_file, "w") as f:
            f.write(str(update_id))