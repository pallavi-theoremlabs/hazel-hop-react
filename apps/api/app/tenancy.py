"""Request-scoped tenant identity, and the trust boundary it arrives across.

Topology (settled 2026-08-17): the React UI is hosted on Azure and never talks to
this API directly. It cannot — a Databricks App sits behind the workspace auth
proxy, which admits only Databricks identities, and a browser has none of the
three things that would be needed to get one: the end users are banks rather than
workspace members, a SPA bundle cannot hold a service principal secret, and a CORS
preflight is sent without credentials so it is rejected before the real request is
ever attempted.

So an Azure backend-for-frontend sits in between. It holds the service principal
secret, mints the OAuth token, and forwards /api/* here. Two consequences shape
this module:

* **The BFF is the only caller.** It proves that with a shared key, compared in
  constant time. Anything reaching this API without it is refused before a
  connection is opened. This is a second lock rather than the only one — the
  Databricks auth proxy is already in front — but app permissions are workspace
  configuration, and a workspace user with CAN_USE would otherwise be able to
  assert any tenant they liked.

* **The BFF names the tenant**, because it is what authenticated the end user.
  This API has no user model of its own and does not attempt one; it takes an
  org id from a caller it has just authenticated, and validates the shape.

Nothing here weakens the database-side guarantee. Every tenant table is FORCE ROW
LEVEL SECURITY (postgres setup/hazel_schema.sql) keyed on the hop.institution_id
GUC, so a missing or wrong institution yields zero rows rather than another
tenant's. That is the backstop; this is the part that makes the common path
correct rather than merely safe.
"""

from __future__ import annotations

import hmac
import logging
import os
from contextvars import ContextVar
from uuid import UUID

from fastapi import HTTPException, Request

logger = logging.getLogger("uvicorn.error")

INSTITUTION_HEADER = "X-Hazel-Institution-Id"
USER_HEADER = "X-Hazel-User-Id"
ROLE_HEADER = "X-Hazel-Role"
PROXY_KEY_HEADER = "X-Hazel-Proxy-Key"

# ck_user_role in hazel_schema.sql, verbatim. 'SYSTEM' is deliberately absent: it
# is the anonymous-intake context the server chooses for itself, never something a
# caller may ask to be — accepting it here would let the BFF request INSERT rights
# on institution, app_user and onboarding_case.
VALID_ROLES = frozenset({
    "MEMBER_ADMIN",
    "MEMBER_CONTRIBUTOR",
    "MEMBER_VIEWER",
    "INTERNAL_REVIEWER",
    "INTERNAL_RISK",
    "INTERNAL_APPROVER",
    "INTERNAL_ADMIN",
    "INTERNAL_SUPPORT",
})

# Read at import so a missing key is a configuration fact rather than a per-request
# environment lookup. Empty means "not configured", which require_proxy() treats as
# fatal rather than as permission to skip the check.
PROXY_KEY = os.getenv("HAZEL_PROXY_KEY", "").strip()

# The tenant for the request currently being served.
#
# A ContextVar rather than a parameter threaded through the call chain: connection()
# is reached from ~83 call sites across the routers, none of which take an org, and
# giving all of them one would be a large mechanical diff over code that has no
# business knowing about tenancy.
#
# It is set from an *async* dependency, and that is load-bearing rather than
# stylistic. The route handlers here are sync `def`, so FastAPI runs them via
# run_in_threadpool, which copies the calling task's context at call time. A
# ContextVar set inside a sync dependency would be set in that dependency's own
# threadpool context and would not be visible to the handler's. Set from the event
# loop task, it propagates into both.
_current_session: ContextVar[tuple[str | None, str | None, str] | None] = ContextVar(
    "hazel_current_session", default=None
)

# The anonymous-intake context hazel_schema.sql defines: no institution, no user,
# and the literal role 'SYSTEM'. Its p_intake policies are INSERT-only and its
# p_tenant policies match nothing, so this sees no existing tenant data — which is
# what makes it safe as the context for the public inquiry form and for startup
# checks that only assert schema shape.
SYSTEM_SESSION: tuple[str | None, str | None, str] = (None, None, "SYSTEM")


def current_session() -> tuple[str | None, str | None, str]:
    """The (institution_id, user_id, role) for this request.

    Deliberately raises rather than falling back to SYSTEM. A fallback would mean a
    route that forgot its dependency quietly runs with a context that can insert
    into three tables, which is the one failure this module exists to prevent.
    """
    session = _current_session.get()
    if session is None:
        raise RuntimeError(
            "No session context for this request. Routes that touch tenant data must "
            "declare dependencies=[Depends(require_tenant)]; work outside a request "
            "must pass connection(session=...) explicitly."
        )
    return session


def set_current_session(institution_id: str, user_id: str | None, role: str) -> None:
    _current_session.set((institution_id, user_id, role))


def _valid_uuid(value: str) -> str | None:
    """Normalise to canonical UUID text, or None.

    The value reaches Postgres as a bound parameter, so this is not about
    injection. It is about which error the caller gets: an unparseable value would
    otherwise arrive as a set_config that succeeds, then an RLS predicate that
    matches nothing, and present as "my data disappeared" instead of "that is not
    an institution id".
    """
    try:
        return str(UUID(value))
    except (ValueError, AttributeError, TypeError):
        return None


async def require_proxy(request: Request) -> None:
    """Authenticate the Azure BFF. Applied to every /api route that touches data.

    Public routes use this alone: a prospective member has no tenant yet, so there
    is no org to assert, but the request must still have come from the BFF.
    """
    if not PROXY_KEY:
        # Refused rather than defaulted open. An unconfigured key is the state a
        # fresh deploy is in, and treating it as "no check needed" would ship an
        # API that is wide open exactly when nobody has looked at it yet.
        logger.error("[Hazel] HAZEL_PROXY_KEY is not set; refusing all API requests")
        raise HTTPException(
            503,
            "This API is not configured to accept requests. HAZEL_PROXY_KEY is unset.",
        )

    presented = request.headers.get(PROXY_KEY_HEADER, "")
    # compare_digest, not ==. String equality short-circuits on the first differing
    # byte, which leaks the shared key one byte at a time to a caller who can time
    # the response.
    if not hmac.compare_digest(presented, PROXY_KEY):
        raise HTTPException(401, "Unauthorized")


async def require_tenant(request: Request) -> None:
    """Authenticate the BFF and establish the session context for this request.

    The three values map onto the session contract hazel_schema.sql documents. The
    BFF supplies them because it is what authenticated the end user against Entra —
    app_user.external_identity_id is an Entra object id, so the user row and the
    token subject are the same identity by construction.
    """
    await require_proxy(request)

    raw = request.headers.get(INSTITUTION_HEADER, "").strip()
    if not raw:
        raise HTTPException(401, f"{INSTITUTION_HEADER} is required.")

    institution_id = _valid_uuid(raw)
    if institution_id is None:
        raise HTTPException(400, f"{INSTITUTION_HEADER} is not a valid UUID.")

    # Optional: internal staff belong to no institution, and ck_user_scope in the
    # schema enforces exactly that, so a missing user id is a legitimate state
    # rather than a defect.
    user_id = _valid_uuid(request.headers.get(USER_HEADER, "").strip() or "")

    role = request.headers.get(ROLE_HEADER, "").strip()
    if role not in VALID_ROLES:
        raise HTTPException(400, f"{ROLE_HEADER} is not a recognised role.")

    set_current_session(institution_id, user_id, role)
