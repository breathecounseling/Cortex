
---

# 🔹 Step 3: Executor README.md

```markdown
# Executor

Executor is the AI worker engine inside Cortex.  
It listens for tasks, routes them to plugins, and handles execution, logging, and approvals.

## Directory Structure
- `middleware/` – core router & scheduler
- `plugins/` – modular task workers
- `connectors/` – integrations (Drive, Sheets, Telegram, OpenAI)
- `runtime/` – Docker/Cloud Run runners
- `approvals/` – approval workflows
- `audit/` – logging + changelogs

## Local Development
1. Copy `.env.template` → `.env`
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
