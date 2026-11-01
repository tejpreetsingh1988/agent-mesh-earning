"""FastAPI factory: health + Agent Card + task endpoint.

Day 3: Scout and Analyst pass a handler; Critic/Writer/Orchestrator
still use the 501 stub until Day 4/5. A handler takes the task
payload dict and returns a JSON-serialisable result dict (an
EvidencePack for Scout, an Analysis for Analyst). The handler is
deliberately NOT an LLM call in v1 — logic is in mesh/scout.py and
mesh/analyst.py, so it is testable without a model.
"""
import uuid
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from .auth import is_authorized
from .cards import CARDS

def create_app(agent_name: str, handler=None) -> FastAPI:
    app = FastAPI(title=f"earnings-{agent_name}")
    card = CARDS[agent_name]

    @app.get("/health")
    def health():
        return {"status": "ok", "agent": agent_name, "version": "0.1.0-day3" if handler else "0.1.0-day1"}

    @app.get("/.well-known/agent.json")
    def agent_card():
        return card

    @app.get("/")
    def root():
        return {"agent": agent_name, "card": "/.well-known/agent.json", "health": "/health",
                "note": "Day 3: Scout + Analyst live; Critic/Writer/Orchestrator land Day 4/5." if handler else "Day 1 stub — agent logic lands Day 3-5 (see ARCHITECTURE.md)."}

    @app.post("/tasks/send")
    def tasks_send(payload: dict, request: Request):
        task_id = str(uuid.uuid4())
        if not is_authorized(request.headers):
            return JSONResponse(status_code=401, content={"task_id": task_id, "state": "failed",
                    "error": "Unauthorized: set AGENT_API_TOKEN in .env and send Authorization: Bearer <token>."})
        if handler is None:
            return JSONResponse(status_code=501, content={"task_id": task_id, "state": "failed",
                    "error": "Agent logic not yet implemented. See ARCHITECTURE.md Day 4-5."})
        try:
            result = handler(payload)
        except Exception as e:
            return JSONResponse(status_code=500, content={"task_id": task_id, "state": "failed", "error": str(e)})
        return {"task_id": task_id, "state": "completed", "result": result}
    return app
