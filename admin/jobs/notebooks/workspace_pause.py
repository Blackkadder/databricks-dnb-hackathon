"""Pause workspace automation and compute without deleting resources.

Uses workspace-level admin credentials. Every visible resource is checked; run as a
workspace admin so that the inventory covers the entire workspace.
"""
from copy import deepcopy
import json
import time
from urllib.parse import quote


class PauseError(RuntimeError):
    pass


def _api(client, method, path, *, query=None, body=None):
    kwargs = {}
    if query is not None:
        kwargs["query"] = query
    if body is not None:
        kwargs["body"] = body
    return client.api_client.do(method, path, **kwargs) or {}


def _pages(client, path, key, query=None):
    query = dict(query or {})
    seen = set()
    while True:
        page = _api(client, "GET", path, query=query)
        yield from page.get(key, [])
        token = page.get("next_page_token")
        if not token:
            if page.get("has_more"):
                raise PauseError(f"Incomplete pagination from {path}")
            break
        if token in seen:
            raise PauseError(f"Repeated pagination token from {path}")
        seen.add(token)
        query["page_token"] = token


def paused_job_settings(settings):
    """Return only trigger settings that need changing, preserving their fields."""
    changes = {}
    for field in ("schedule", "continuous", "trigger"):
        if settings.get(field) and settings[field].get("pause_status") != "PAUSED":
            changes[field] = {**deepcopy(settings[field]), "pause_status": "PAUSED"}
    return changes


def paused_pipeline_spec(spec):
    changes = deepcopy(spec)
    changes["continuous"] = False
    if changes.get("trigger", {}).get("cron") is not None:
        changes["trigger"] = {"manual": {}}
    return changes


def _managed_pipeline(spec):
    return bool(spec.get("pipeline_type") == "DATABASE_TABLE_SYNC"
                or "database_table_sync" in (spec.get("managed_definition") or {}))


def _pipeline_automated(spec):
    # continuous is an execution mode, rather than an independent scheduler.
    # Managed synced-table pipelines cannot be edited through Pipelines APIs;
    # stopping their update leaves them IDLE until explicitly started again.
    return bool((spec.get("continuous") and not _managed_pipeline(spec))
                or "cron" in (spec.get("trigger") or {}))


def inventory(client):
    jobs = list(_pages(client, "/api/2.2/jobs/list", "jobs", {"limit": 100}))
    # Read individual settings, because list responses may omit large settings.
    jobs = [_api(client, "GET", "/api/2.2/jobs/get", query={"job_id": j["job_id"]}) for j in jobs]
    runs = list(_pages(client, "/api/2.2/jobs/runs/list", "runs", {"active_only": True, "limit": 25}))
    apps = list(_pages(client, "/api/2.0/apps", "apps"))
    pipeline_list = list(_pages(client, "/api/2.0/pipelines", "statuses", {"max_results": 100}))
    pipelines = [_api(client, "GET", f'/api/2.0/pipelines/{p["pipeline_id"]}') for p in pipeline_list]
    return {"jobs": jobs, "runs": runs, "apps": apps, "pipelines": pipelines}


def blockers(state, current_run_id=None):
    problems = []
    for job in state["jobs"]:
        if paused_job_settings(job.get("settings", {})):
            problems.append(f'job {job["job_id"]} has an unpaused trigger')
    for run in state["runs"]:
        if str(run["run_id"]) != str(current_run_id):
            problems.append(f'run {run["run_id"]} remains active')
    for app in state["apps"]:
        compute = app.get("compute_status") or {}
        if compute.get("state") != "STOPPED" or compute.get("active_instances", 0):
            problems.append(f'app {app["name"]} compute state {compute}')
    for pipeline in state["pipelines"]:
        if _pipeline_automated(pipeline.get("spec", {})):
            problems.append(f'pipeline {pipeline["pipeline_id"]} has automatic updates enabled')
        if pipeline.get("state") != "IDLE":
            problems.append(f'pipeline {pipeline["pipeline_id"]} state {pipeline.get("state")}')
    return problems


def pause_workspace(client, *, run_live=False, current_run_id=None,
                    timeout_seconds=1200, poll_seconds=10, emit=print):
    """Snapshot, pause, stop, and verify; raise if any operation or check fails.

    Snapshots are emitted as JSON in task output before any change. Concurrent
    manual resource creation/start is outside the scope of pausing automation,
    but verification inventories the workspace again and detects it.
    """
    if timeout_seconds <= 0 or poll_seconds < 0:
        raise ValueError("timeout_seconds must be positive; poll_seconds nonnegative")
    state = inventory(client)
    emit(json.dumps({"event": "before", "run_live": run_live,
                     "current_run_id": current_run_id, "inventory": state}, default=str))
    counts = {key: len(value) for key, value in state.items()}
    if not run_live:
        result = {"mode": "DRY_RUN", "counts": counts,
                  "changes_required": blockers(state, current_run_id)}
        emit(json.dumps(result))
        return result
    errors = []

    def attempt(label, method, path, body=None):
        try:
            _api(client, method, path, body=body)
            emit(json.dumps({"event": "requested", "action": label}))
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            emit(json.dumps({"event": "error", "action": label, "error": str(exc)}))

    # Pause future automation before canceling active work.
    for job in state["jobs"]:
        changes = paused_job_settings(job.get("settings", {}))
        if changes:
            attempt(f'pause job {job["job_id"]}', "POST", "/api/2.2/jobs/update",
                    {"job_id": job["job_id"], "new_settings": changes})
    for pipeline in state["pipelines"]:
        if _pipeline_automated(pipeline.get("spec", {})):
            body = paused_pipeline_spec(pipeline["spec"])
            if pipeline.get("last_modified") is not None:
                body["expected_last_modified"] = pipeline["last_modified"]
            attempt(f'disable automation for pipeline {pipeline["pipeline_id"]}', "PUT",
                    f'/api/2.0/pipelines/{pipeline["pipeline_id"]}', body)
    # Re-list runs after pausing: catch runs launched during the inventory.
    active_runs = list(_pages(client, "/api/2.2/jobs/runs/list", "runs", {"active_only": True, "limit": 25}))
    own_job_ids = {run.get("job_id") for run in active_runs
                   if str(run["run_id"]) == str(current_run_id)}
    canceled_jobs = set()
    for run in active_runs:
        if str(run["run_id"]) == str(current_run_id):
            continue
        job_id = run.get("job_id")
        if job_id is not None and job_id not in own_job_ids:
            if job_id not in canceled_jobs:
                attempt(f'cancel all runs for job {job_id}', "POST", "/api/2.2/jobs/runs/cancel-all",
                        {"job_id": job_id, "all_queued_runs": True})
                canceled_jobs.add(job_id)
        else:
            attempt(f'cancel run {run["run_id"]}', "POST", "/api/2.2/jobs/runs/cancel", {"run_id": run["run_id"]})
    for app in state["apps"]:
        if (app.get("compute_status") or {}).get("state") != "STOPPED":
            attempt(f'stop app {app["name"]}', "POST", f'/api/2.0/apps/{quote(app["name"], safe="")}/stop')
    for pipeline in state["pipelines"]:
        # Always request stop: it also covers an update started since inventory.
        attempt(f'stop pipeline {pipeline["pipeline_id"]}', "POST", f'/api/2.0/pipelines/{pipeline["pipeline_id"]}/stop')
    deadline = time.monotonic() + timeout_seconds
    while True:
        final = inventory(client)
        pending = blockers(final, current_run_id)
        emit(json.dumps({"event": "verification", "pending": pending, "errors": errors}))
        if errors and pending:
            # Permanent API errors cannot be resolved by waiting for compute.
            raise PauseError(json.dumps({"errors": errors, "pending": pending}))
        if not pending:
            if errors:
                raise PauseError("Operations reported errors despite quiescent verification: " + "; ".join(errors))
            result = {"mode": "LIVE", "verified": True, "counts": {key: len(value) for key, value in final.items()},
                      "excluded_current_run_id": current_run_id,
                      "managed_pipeline_modes_retained": [
                          {"pipeline_id": pipeline["pipeline_id"],
                           "continuous": pipeline.get("spec", {}).get("continuous", False)}
                          for pipeline in final["pipelines"]
                          if _managed_pipeline(pipeline.get("spec", {}))]}
            emit(json.dumps(result))
            return result
        if time.monotonic() >= deadline:
            raise PauseError(json.dumps({"errors": errors, "pending": pending}))
        # Bulk cancellation may race a queued run becoming active. Reissue an
        # individual cancellation for anything still active, excluding this run.
        for run in final["runs"]:
            if (str(run["run_id"]) != str(current_run_id)
                    and (run.get("state") or {}).get("life_cycle_state") != "TERMINATING"):
                attempt(f'cancel remaining run {run["run_id"]}', "POST",
                        "/api/2.2/jobs/runs/cancel", {"run_id": run["run_id"]})
        time.sleep(min(poll_seconds, max(0, deadline - time.monotonic())))
