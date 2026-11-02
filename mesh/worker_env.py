"""Read a Cloudflare Worker variable or secret from the Worker env object.

Why this module exists: in a Python Worker, dashboard variables and
secrets live on the Worker env object — `self.env` on a
WorkerEntrypoint, or the `workers.env` module object (Cloudflare's
own Django example reads a secret as `env.DJANGO_SECRET_KEY` at
import time). They are NOT placed into os.environ, and the asgi
adapter does not hand env to the FastAPI app, so existing code
that reads os.environ cannot see a dashboard secret. The fix is
to read the value here, explicitly, and pass it to the code that
needs it (today: the Writer passes it as build_story_async's
api_key). The function never raises and never returns a
non-string: a missing module, a missing name, or a non-string
binding all mean None, and the caller falls back to its
no-key behavior (for the Writer: the deterministic story).
The value is never logged or put in a payload.
"""

import os


def worker_env_value(name: str) -> str | None:
    """Return the Worker env value for `name`, or None.

    Locally (Docker, tests, plain Python) the `workers` module does
    not exist, so this returns None and callers use their
    os.environ path unchanged.
    """
    try:
        from workers import env as _worker_env
    except ImportError:
        return None
    try:
        value = getattr(_worker_env, name, None)
    except Exception:
        return None
    if isinstance(value, str) and value:
        return value
    return None


def ai_binding():
    """Return the Workers AI binding (env.AI), or None.

    Same guarded pattern as worker_env_value: locally the
    `workers` module does not exist, so this returns None and
    callers skip the Workers AI attempt. A binding object is
    returned as-is (it is not a string, so worker_env_value's
    string check would wrongly reject it). If the binding is
    present but unusable, the caller's try/except handles it —
    a Workers AI failure falls through to OpenRouter, never
    breaks the briefing.
    """
    try:
        from workers import env as _worker_env
    except ImportError:
        return None
    try:
        return getattr(_worker_env, "AI", None)
    except Exception:
        return None


def effective_api_key(name: str = "OPENROUTER_API_KEY") -> str | None:
    """Worker env value first, process environment second.

    Lets one call site work in both runtimes: a Worker secret when
    running as a Worker, the host .env when running in Docker.
    """
    return worker_env_value(name) or os.environ.get(name) or None
