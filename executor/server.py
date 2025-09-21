# server.py
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict, Any
import subprocess

from executor.plugins.extend_plugin import extend_plugin
from executor.builder import main as build_plugin

app = FastAPI(title="Cortex Executor API")

class ExtendRequest(BaseModel):
    plugin: str
    goal: str

@app.post("/extend")
def extend(req: ExtendRequest) -> Dict[str, Any]:
    return extend_plugin(req.plugin, req.goal)

@app.post("/build")
def build(req: Dict[str, str]):
    # adapt if builder takes args
    build_plugin()
    return {"status": "ok", "msg": "builder ran"}

@app.post("/sync")
def sync() -> Dict[str, Any]:
    try:
        subprocess.check_call(["git", "pull"])
        subprocess.check_call(["git", "push"])
        return {"status": "ok", "msg": "repo synced"}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "msg": str(e)}