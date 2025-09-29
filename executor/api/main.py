from fastapi import FastAPI
from executor.core.router import route

app = FastAPI(title="Cortex Executor API")

@app.get("/")
def healthcheck():
    return {"status": "ok"}

@app.post("/execute")
def execute(user_text: str):
    result = route(user_text, session="api")
    return {"result": result}