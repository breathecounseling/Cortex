import os
from connectors.telegram import send_telegram

def handle_task(task_text: str):
    if "phalanx" in task_text.lower():
        return "Routed to Phalanx plugin"
    if "report" in task_text.lower():
        return "Routed to BizOps plugin"
    return "Routed to Cortex plugin"

if __name__ == "__main__":
    task = "Test routing"
    result = handle_task(task)
    send_telegram(os.getenv("OWNER_CHAT_ID"), f"Task: {task}\nResult: {result}")
