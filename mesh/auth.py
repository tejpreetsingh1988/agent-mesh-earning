"""Bearer-token auth, v1 — defence in depth, not the whole story.

Design (see docs/decisions/006-hosting-auth.md, to be written with
the Cloudflare step):
- Cloudflare Access is the human gate in front of the tunnelled UI.
- This token is the second layer: a request that somehow bypasses
  Access (origin IP discovered, direct localhost exposure) still
  fails without it.
- It is OFF by default: if AGENT_API_TOKEN is unset or empty,
  every call is allowed, so local dev and the existing tests keep
  working with no change. Set it in the PC's git-ignored .env and
  Compose passes it to every service; then /tasks/send,
  /tasks/stream, and /tools/call require it, while /health and
  Agent Cards stay open (healthchecks and discovery must not
  need a secret).
- One shared token for v1: simple, all-or-nothing. That is a
  known limitation — it gives no per-user identity, no MFA, and
  a leaked token is full access until rotated. Rotation = change
  the token in .env and restart the stack. Do not put the token
  in git, in a zip, in a trace, or in chat.
"""
import hmac
import os


def token_from_env() -> str:
    return (os.environ.get("AGENT_API_TOKEN") or "").strip()


def auth_headers() -> dict:
    """Headers a trusted in-stack caller adds, so services can
    call each other when the token is set. Empty when auth is off."""
    token = token_from_env()
    return {"Authorization": f"Bearer {token}"} if token else {}


def is_authorized(headers, token: str | None = None) -> bool:
    """True if auth is off (no token configured) or the request
    carries `Authorization: Bearer <token>` for the configured token.

    headers may be a FastAPI/Starlette Headers object or a plain dict.
    Comparison is constant-time so a wrong token leaks no timing signal.
    """
    expected = token if token is not None else token_from_env()
    if not expected:
        return True
    try:
        presented = headers.get("authorization", "")
    except Exception:
        presented = ""
    if not isinstance(presented, str):
        return ""
    return hmac.compare_digest(presented.strip(), f"Bearer {expected}")
