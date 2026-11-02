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

class _CorsMiddleware:
    """Minimal CORS for the browser frontend (Cloudflare Pages
    calls the Orchestrator Worker cross-origin). Pure ASGI, no
    new dependency, and deliberately allow-all: these proof
    endpoints are public and carry no user data. Docker agents
    keep cors=False (the default) and are unaffected."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope["method"] == "OPTIONS":
            async def _send(message):
                if message["type"] == "http.response.start":
                    headers = [(k, v) for k, v in message.get("headers", [])
                               if k.lower() != b"access-control-allow-origin"]
                    headers += [(b"access-control-allow-origin", b"*"),
                                (b"access-control-allow-methods", b"GET, POST, OPTIONS"),
                                (b"access-control-allow-headers", b"Content-Type, Authorization")]
                    message = {**message, "headers": headers}
                await send(message)
            await _send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return

        async def _send_with_cors(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"access-control-allow-origin", b"*"))
                message = {**message, "headers": headers}
            await send(message)
        await self.app(scope, receive, _send_with_cors)


def create_app(agent_name: str, handler=None, async_handler=None, cors=False) -> FastAPI:
    """handler: sync callable (Docker agents, Analyst Worker).
    async_handler: awaitable callable (Scout Worker v2 — its tool
    calls are async fetch, which a sync endpoint cannot await in
    a Worker: no threads, no sync XHR). When async_handler is
    given, /tasks/send is an async endpoint; otherwise it stays
    exactly the sync endpoint it has always been.
    cors=True wraps the app in _CorsMiddleware (Orchestrator
    Worker only — the Pages frontend calls it cross-origin)."""
    app = FastAPI(title=f"earnings-{agent_name}")
    if cors:
        app.add_middleware(_CorsMiddleware)
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

    def _unauthorized(task_id):
        return JSONResponse(status_code=401, content={"task_id": task_id, "state": "failed",
                "error": "Unauthorized: set AGENT_API_TOKEN in .env and send Authorization: Bearer <token>."})

    def _unimplemented(task_id):
        return JSONResponse(status_code=501, content={"task_id": task_id, "state": "failed",
                "error": "Agent logic not yet implemented. See ARCHITECTURE.md Day 4-5."})

    if async_handler is not None:
        @app.post("/tasks/send")
        async def tasks_send_async(payload: dict, request: Request):
            task_id = str(uuid.uuid4())
            if not is_authorized(request.headers):
                return _unauthorized(task_id)
            try:
                result = await async_handler(payload)
            except Exception as e:
                return JSONResponse(status_code=500, content={"task_id": task_id, "state": "failed", "error": str(e)})
            return {"task_id": task_id, "state": "completed", "result": result}
    else:
        @app.post("/tasks/send")
        def tasks_send(payload: dict, request: Request):
            task_id = str(uuid.uuid4())
            if not is_authorized(request.headers):
                return _unauthorized(task_id)
            if handler is None:
                return _unimplemented(task_id)
            try:
                result = handler(payload)
            except Exception as e:
                return JSONResponse(status_code=500, content={"task_id": task_id, "state": "failed", "error": str(e)})
            return {"task_id": task_id, "state": "completed", "result": result}
    return app
