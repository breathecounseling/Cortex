# executor/ai/router.py
# PATCH START — Dynamic model routing with Boost Mode and usage logging
from __future__ import annotations
import os, time, json
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
LOG_FILE = os.getenv("CORTEX_USAGE_LOG", "usage_log.jsonl")

DEFAULT_MODEL = "gpt-4o"
BOOST_MODEL = "gpt-5"
BOOST_THRESHOLD = int(os.getenv("CORTEX_BOOST_THRESHOLD", "5000"))  # token count or reasoning complexity

def _log_usage(model: str, prompt: str, tokens_in: int, tokens_out: int):
    record = {
        "timestamp": time.time(),
        "model": model,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "prompt_snippet": prompt[:100],
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

def respond(prompt: str, boost: bool = False, complexity: int = 0) -> str:
    """
    boost=True or complexity>BOOST_THRESHOLD triggers GPT-5 instead of GPT-4o.
    """
    model = BOOST_MODEL if boost or complexity > BOOST_THRESHOLD else DEFAULT_MODEL
    response = client.responses.create(model=model, input=prompt)
    text = response.output_text
    try:
        _log_usage(model, prompt, response.usage.input_tokens, response.usage.output_tokens)
    except Exception:
        pass
    return text
# PATCH END