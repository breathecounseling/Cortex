from openai import OpenAI
import os
import json
from dotenv import load_dotenv
from executor.plugins.builder import builder

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Define available tools
TOOLS = [
    {
        "type": "function",
        "name": "build_plugin",
        "description": "Create a new Executor plugin with the given name and purpose.",
        "parameters": {
            "type": "object",
            "properties": {
                "plugin_name": {"type": "string"},
                "purpose": {"type": "string"}
            },
            "required": ["plugin_name", "purpose"]
        }
    }
]

def ask_executor(prompt: str):
    response = client.responses.create(
        model="gpt-5",
        instructions="You are Cortex Executor. Route tasks or build plugins when requested.",
        input=prompt,
        tools=TOOLS
    )

    # Check if model requested a function call
    for item in response.output:
        if item.type == "function_call" and item.name == "build_plugin":
            args = json.loads(item.arguments)  # parse JSON string into dict
            result = builder.build_plugin(
                plugin_name=args["plugin_name"],
                purpose=args["purpose"]
            )
            return result


    return {"status": "ok", "message": response.output_text}


if __name__ == "__main__":
    # Example: Ask Executor to build a new plugin
    result = ask_executor("Build plugin calendar to sync Google Calendar")
    print(result)
