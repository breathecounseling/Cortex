"""
OpenAI connector
Thin wrapper around the OpenAI API.
"""

def complete(prompt: str):
    print(f"[OpenAI] Would complete prompt: {prompt[:30]}...")
    return "This is a dummy OpenAI completion."

