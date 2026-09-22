# Copyright 2026 Databricks, Inc.
# SPDX-License-Identifier: Apache-2.0
"""Lakebase connection helpers with OAuth token refresh.

Lakebase database credentials are short-lived OAuth tokens (1-hour expiry), so a
long-lived connection pool must refresh them. This module is imported by both the
Lakebase notebook (``notebooks/lakebase_lab.py``) and the offline test suite
(``tests/test_notebook_logic.py``).

Design notes
------------
* ``needs_refresh`` is a **pure** function — the 50-minute decision, trivially testable.
* ``LakebaseTokenProvider`` caches a token and regenerates it (via an injected
  ``credential_fn``) once it ages past the refresh threshold.
* ``build_engine`` wires a SQLAlchemy engine whose ``do_connect`` listener asks the
  provider for a fresh token on every physical connect — so the credential generator
  is called *before* the connection opens whenever the token is stale.

The module has **no import-time side effects** (no WorkspaceClient, no network), so it
is safe to import in unit tests.
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable, Optional

# OAuth tokens are valid for 1 hour; refresh at 50 minutes to leave headroom.
TOKEN_TTL_SECONDS = 3600
REFRESH_AFTER_SECONDS = 3000

# Project-name prefix for the hackathon lab.
PROJECT_ID_PREFIX = "lakebase-lab"


def derive_project_id(
    user_id: str,
    user_name: str = "",
    prefix: str = PROJECT_ID_PREFIX,
) -> str:
    """Build a Lakebase project id that is unique per user within the workspace.

    Only the *project* name shares a namespace across users (branches, the ``nyc_taxi``
    database, and endpoints live inside a project and never collide), so the project is
    the one thing that needs a per-user suffix.

    Uniqueness is **guaranteed** by ``user_id`` — the Databricks numeric user id, which the
    platform guarantees is unique within the account/workspace. The sanitized email
    local-part is included only for human readability and never affects uniqueness. The
    function is pure and deterministic, so re-runs and teardown resolve to the same project.

    Example::

        derive_project_id("4831207756699123", "sridhar.paladugu@databricks.com")
        # -> "lakebase-lab-sridhar-paladugu-4831207756699123"
    """
    local = user_name.split("@", 1)[0].lower()
    slug = re.sub(r"[^a-z0-9]+", "-", local).strip("-")[:20].rstrip("-") or "user"
    return f"{prefix}-{slug}-{user_id}"


def needs_refresh(
    token_issued_at: float,
    now: float,
    refresh_after: int = REFRESH_AFTER_SECONDS,
) -> bool:
    """Return True when a token issued at ``token_issued_at`` should be refreshed.

    Pure function: no I/O, no globals. A token is refreshed once its age reaches the
    ``refresh_after`` threshold (default 50 minutes).
    """
    return (now - token_issued_at) >= refresh_after


class LakebaseTokenProvider:
    """Caches a short-lived OAuth token and refreshes it when it ages out.

    Parameters
    ----------
    endpoint:
        Lakebase endpoint resource name
        (``projects/{id}/branches/{id}/endpoints/{id}``).
    credential_fn:
        Callable ``(endpoint) -> token_str``. In production this wraps
        ``WorkspaceClient.postgres.generate_database_credential``; in tests it is a mock.
    clock:
        Callable returning "now" as epoch seconds (injectable for tests).
    refresh_after:
        Age in seconds at which a cached token is regenerated.
    """

    def __init__(
        self,
        endpoint: str,
        credential_fn: Callable[[str], str],
        clock: Callable[[], float] = time.time,
        refresh_after: int = REFRESH_AFTER_SECONDS,
    ) -> None:
        self._endpoint = endpoint
        self._credential_fn = credential_fn
        self._clock = clock
        self._refresh_after = refresh_after
        self._token: Optional[str] = None
        self._issued_at: float = 0.0

    def get_token(self) -> str:
        """Return a valid token, regenerating it first if missing or stale."""
        now = self._clock()
        if self._token is None or needs_refresh(
            self._issued_at, now, self._refresh_after
        ):
            self._token = self._credential_fn(self._endpoint)
            self._issued_at = now
        return self._token


def workspace_credential_fn(workspace_client: Any) -> Callable[[str], str]:
    """Adapt a Databricks ``WorkspaceClient`` into a ``credential_fn``."""

    def _generate(endpoint: str) -> str:
        return workspace_client.postgres.generate_database_credential(
            endpoint=endpoint
        ).token

    return _generate


def make_token_injector(token_provider: "LakebaseTokenProvider"):
    """Return a SQLAlchemy ``do_connect`` listener that injects a fresh token.

    The listener asks the provider for a token (regenerated when stale) and writes it as
    the connection password before the physical connect opens.
    """

    def _inject(dialect, conn_rec, cargs, cparams):  # noqa: ANN001
        cparams["password"] = token_provider.get_token()

    return _inject


def build_engine(
    host: str,
    database: str,
    user: str,
    token_provider: LakebaseTokenProvider,
    **engine_kwargs: Any,
):
    """Build a SQLAlchemy engine that injects a fresh token on every connect.

    The ``do_connect`` event fires before each physical connection is opened; the
    listener pulls a token from ``token_provider`` (which regenerates it when stale),
    so credentials never expire underneath the pool.
    """
    from sqlalchemy import create_engine, event

    url = f"postgresql+psycopg://{user}@{host}:5432/{database}"
    engine = create_engine(
        url,
        connect_args={"sslmode": "require"},
        pool_pre_ping=True,
        **engine_kwargs,
    )

    injector = make_token_injector(token_provider)
    event.listen(engine, "do_connect", injector)
    engine._token_injector = injector  # exposed for testing/introspection
    return engine
