"""
OpenAI Responses API connector for Executor.
Registers Builder and Extender as tools and provides ask_executor().
"""

import os
import json
from dotenv import load_dotenv
from openai import OpenAI

# Load .env from repo root
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY missing from .env")

client = OpenAI(api_key=OPENAI_API_KEY)

# Import Builder and Extender
from executor.plugins.builder import builder, extend_plugin

# Tool registry
TOOLS = [
    {
        "type": "function",
        "name": "build_plugin",
        "description": "Create a new Executor plugin.",
        "parameters": {
            "type": "object",
            "properties": {
                "plugin_name": {"type": "string"},
                "purpose": {"type": "string"}
            },
            "required": ["plugin_name", "purpose"]
        }
    },
    {
        "type": "function",
        "name": "extend_plugin",
        "description": "Extend an existing Executor plugin with a new feature.",
        "parameters": {
            "type": "object",
            "properties": {
                "plugin_name": {"type": "string"},
                "new_feature": {"type": "string"}
            },
            "required": ["plugin_name", "new_feature"]
        }
    }
]

SYSTEM_INSTRUCTIONS = (
    "You are Cortex Executor, an AI system that writes and edits plugins. "
    "If the user request is vague, ask clarifying questions. "
    "When calling tools, provide the correct parameters. "
    "When fixing code, preserve all working functions and only fix broken ones. "
    "When outputting code, return ONLY the complete corrected file."
)

def ask_executor(prompt: str, thread_id: str = "default"):
    """
    High-level interface to the OpenAI Responses API.
    Routes natural language input to freeform responses or tool calls.
    """
    response = client.responses.create(
        model="gpt-5",
        instructions=SYSTEM_INSTRUCTIONS,
        input=prompt,
        tools=TOOLS,
        store=False
    )

    # Default result
    out_text = getattr(response, "output_text", None) or ""
    result = {"status": "ok", "response_text": out_text, "raw": response}

    # Inspect function calls
    for item in response.output:
        if item.type == "function_call":
            try:
                args = json.loads(item.arguments)
            except Exception:
                args = {}

            if item.name == "build_plugin":
                return builder.build_plugin(
                    plugin_name=args.get("plugin_name", ""),
                    purpose=args.get("purpose", "")
                )
            elif item.name == "extend_plugin":
                return extend_plugin.extend_plugin(
                    plugin_name=args.get("plugin_name", ""),
                    new_feature=args.get("new_feature", "")
                )

            result = {
                "status": "function_call",
                "name": item.name,
                "arguments": args,
                "raw": response
            }
            break

    return result


if __name__ == "__main__":
    print("Cortex Executor REPL (type 'quit' to exit)")
    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in ["quit", "exit"]:
            break
        output = ask_executor(user_input)
        print("Executor:", output)
