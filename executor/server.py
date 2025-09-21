# executor/connectors/server.py
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Dict, Any
import subprocess
import os

from executor.plugins.extend_plugin import extend_plugin
from executor.plugins.builder import main as build_plugin

app = FastAPI(title="Cortex Executor API")

# ---------- API MODELS ----------
class ExtendRequest(BaseModel):
    plugin: str
    goal: str

# ---------- API ENDPOINTS ----------
@app.post("/extend")
def extend(req: ExtendRequest) -> Dict[str, Any]:
    return extend_plugin(req.plugin, req.goal)

@app.post("/build")
def build() -> Dict[str, Any]:
    try:
        build_plugin()
        return {"status": "ok", "msg": "builder ran"}
    except Exception as e:
        return {"status": "error", "msg": str(e)}

@app.post("/sync")
def sync() -> Dict[str, Any]:
    try:
        subprocess.check_call(["git", "pull"])
        subprocess.check_call(["git", "push"])
        return {"status": "ok", "msg": "repo synced"}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "msg": str(e)}

# ---------- STATIC FRONTEND ----------
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
FRONTEND_DIST = os.path.abspath(FRONTEND_DIST)

if os.path.isdir(FRONTEND_DIST):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIST, html=True), name="static")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        """
        Serve React index.html for any non-API route
        (so React Router works).
        """
        index_file = os.path.join(FRONTEND_DIST, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        return {"status": "error", "msg": "frontend not built"}