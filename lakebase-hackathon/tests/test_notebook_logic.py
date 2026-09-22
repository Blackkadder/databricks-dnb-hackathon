# Copyright 2026 Databricks, Inc.
# SPDX-License-Identifier: Apache-2.0
"""Offline tests for the token-refresh connection manager (spec §5.2).

No live calls to Databricks: the credential generator is mocked and the clock is
injected, so the 50-minute refresh behaviour and the SQLAlchemy ``do_connect`` listener
are verified without a workspace or a database.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# The connection manager lives alongside the notebook.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "notebooks"))

from lakebase_conn import (  # noqa: E402
    PROJECT_ID_PREFIX,
    REFRESH_AFTER_SECONDS,
    LakebaseTokenProvider,
    build_engine,
    derive_project_id,
    make_token_injector,
    needs_refresh,
    workspace_credential_fn,
)

EP = "projects/lakebase-lab-jdoe-123/branches/production/endpoints/primary"


# --- pure decision function -------------------------------------------------


def test_needs_refresh_is_false_before_threshold() -> None:
    assert needs_refresh(0.0, REFRESH_AFTER_SECONDS - 1) is False


def test_needs_refresh_is_true_at_and_after_threshold() -> None:
    assert needs_refresh(0.0, REFRESH_AFTER_SECONDS) is True
    assert needs_refresh(0.0, REFRESH_AFTER_SECONDS + 600) is True


# --- per-user project id derivation -----------------------------------------


def test_derive_project_id_shape_and_readability() -> None:
    pid = derive_project_id("4831207756699123", "sridhar.paladugu@databricks.com")
    assert pid == "lakebase-lab-sridhar-paladugu-4831207756699123"
    assert pid.startswith(PROJECT_ID_PREFIX + "-")
    # Only lowercase letters, digits, and hyphens.
    assert all(c.islower() or c.isdigit() or c == "-" for c in pid)


def test_derive_project_id_is_deterministic() -> None:
    args = ("999", "a.b@x.com")
    assert derive_project_id(*args) == derive_project_id(*args)


def test_derive_project_id_uniqueness_guaranteed_by_user_id() -> None:
    # Two different users whose email local-parts sanitize to the SAME slug still get
    # distinct project ids, because the guaranteed-unique numeric user id is appended.
    a = derive_project_id("111", "john.doe@team-a.com")
    b = derive_project_id("222", "john-doe@team-b.com")
    assert a != b
    assert a.endswith("-111") and b.endswith("-222")


def test_derive_project_id_sanitizes_and_truncates() -> None:
    # Uppercase, dots/plus, and over-length local parts are normalized to a safe slug.
    pid = derive_project_id("7", "Weird.Name+tag.this.is.long.enough@corp.io")
    slug = pid[len(PROJECT_ID_PREFIX) + 1 : -len("-7")]
    assert (
        slug == "weird-name-tag-this"
    )  # lowercased, hyphenated, ≤20 chars, no trailing -
    assert len(slug) <= 20


def test_derive_project_id_empty_local_falls_back_to_user() -> None:
    assert derive_project_id("42", "@nolocal.com") == "lakebase-lab-user-42"


# --- token provider ---------------------------------------------------------


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_provider_generates_once_then_caches() -> None:
    clock = FakeClock(0.0)
    cred = MagicMock(side_effect=["tok-1", "tok-2"])
    provider = LakebaseTokenProvider(EP, cred, clock=clock)

    assert provider.get_token() == "tok-1"  # first call generates
    clock.t = REFRESH_AFTER_SECONDS - 1  # still fresh
    assert provider.get_token() == "tok-1"  # cached, no new call
    assert cred.call_count == 1
    cred.assert_called_with(EP)


def test_provider_refreshes_after_50_minutes() -> None:
    clock = FakeClock(0.0)
    cred = MagicMock(side_effect=["tok-1", "tok-2"])
    provider = LakebaseTokenProvider(EP, cred, clock=clock)

    assert provider.get_token() == "tok-1"
    clock.t = REFRESH_AFTER_SECONDS  # stale
    assert provider.get_token() == "tok-2"  # regenerated
    assert cred.call_count == 2


# --- SQLAlchemy do_connect listener ----------------------------------------


def test_do_connect_injects_current_token() -> None:
    clock = FakeClock(0.0)
    cred = MagicMock(side_effect=["tok-1", "tok-2"])
    provider = LakebaseTokenProvider(EP, cred, clock=clock)
    inject = make_token_injector(provider)

    cparams: dict = {}
    inject(None, None, [], cparams)  # simulate a physical connect
    assert cparams["password"] == "tok-1"
    assert cred.call_count == 1


def test_do_connect_refreshes_token_when_stale() -> None:
    clock = FakeClock(0.0)
    cred = MagicMock(side_effect=["tok-1", "tok-2"])
    provider = LakebaseTokenProvider(EP, cred, clock=clock)
    inject = make_token_injector(provider)

    cparams: dict = {}
    inject(None, None, [], cparams)  # t=0 -> tok-1
    assert cparams["password"] == "tok-1"

    clock.t = REFRESH_AFTER_SECONDS  # age past 50 min
    inject(None, None, [], cparams)  # -> regenerates before connect
    assert cparams["password"] == "tok-2"
    assert cred.call_count == 2


def test_build_engine_registers_do_connect_listener() -> None:
    from sqlalchemy import event

    provider = LakebaseTokenProvider(EP, MagicMock(return_value="tok"))
    engine = build_engine("h.example", "nyc_taxi", "user@x.com", provider)
    # the exact listener the engine will fire on connect is exposed for verification
    assert event.contains(engine, "do_connect", engine._token_injector)


# --- WorkspaceClient adapter ------------------------------------------------


def test_workspace_credential_fn_calls_sdk() -> None:
    w = MagicMock()
    w.postgres.generate_database_credential.return_value.token = "sdk-token"

    fn = workspace_credential_fn(w)
    assert fn(EP) == "sdk-token"
    w.postgres.generate_database_credential.assert_called_once_with(endpoint=EP)
