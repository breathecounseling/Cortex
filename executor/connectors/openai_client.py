"""
OpenAI Responses API connector for Executor.
"""

import os
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def ask_executor(prompt: str):
    """
    Sends a prompt to the OpenAI Responses API and returns the text output.
    """
    response = client.responses.create(
        model="gpt-5",
        instructions="You are Cortex Executor, a system that routes tasks and builds plugins.",
        input=prompt
    )
    return response.output_text

if __name__ == "__main__":
    result = ask_executor("Say hello from the Responses API!")
    print(result)
