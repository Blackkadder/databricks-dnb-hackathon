"""Contract tests for workspace-wide pause semantics using a stateful API fake."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent / "notebooks"))
from workspace_pause import PauseError, pause_workspace, paused_pipeline_spec


class Workspace:
    def __init__(self):
        self.api_client = self
        self.calls = []
        self.fail_stop = False
        self.jobs = [
            {"job_id": 1, "settings": {"schedule": {"pause_status": "UNPAUSED", "quartz_cron_expression": "cron", "timezone_id": "UTC"}}},
            {"job_id": 2, "settings": {"continuous": {"pause_status": "UNPAUSED"}, "trigger": {"pause_status": "UNPAUSED", "file_arrival": {"url": "/Volumes/x"}}}},
        ]
        self.runs = [{"run_id": 10, "job_id": 1}, {"run_id": 11, "job_id": 1}, {"run_id": 12, "job_id": 2}, {"run_id": 13, "job_id": 2}]
        self.apps = [{"name": "app", "compute_status": {"state": "ACTIVE", "active_instances": 1}}]
        self.pipelines = [{"pipeline_id": "pipe", "state": "RUNNING", "last_modified": 123,
                           "spec": {"id": "pipe", "continuous": True, "trigger": {"cron": {"quartz_cron_schedule": "cron"}}, "libraries": [{"file": {"path": "/x.py"}}]}}]

    def do(self, method, path, query=None, body=None):
        self.calls.append((method, path, deepcopy(body)))
        if method == "GET":
            if path.endswith("jobs/list"):
                # Exercise page-token handling.
                return {"jobs": [self.jobs[1]]} if (query or {}).get("page_token") else {"jobs": [self.jobs[0]], "next_page_token": "two"}
            if path.endswith("jobs/get"):
                return deepcopy(next(j for j in self.jobs if j["job_id"] == query["job_id"]))
            if path.endswith("runs/list"):
                return {"runs": deepcopy(self.runs)}
            if path.endswith("/apps"):
                return {"apps": deepcopy(self.apps)}
            if path.endswith("/pipelines"):
                return {"statuses": [{"pipeline_id": "pipe"}]}
            if path.endswith("/pipelines/pipe"):
                return deepcopy(self.pipelines[0])
        if path.endswith("jobs/update"):
            next(j for j in self.jobs if j["job_id"] == body["job_id"])["settings"].update(body["new_settings"])
        elif path.endswith("runs/cancel-all"):
            self.runs = [r for r in self.runs if r["job_id"] != body["job_id"]]
        elif path.endswith("runs/cancel"):
            self.runs = [r for r in self.runs if r["run_id"] != body["run_id"]]
        elif path.endswith("apps/app/stop"):
            if self.fail_stop:
                raise RuntimeError("Denied")
            self.apps[0]["compute_status"] = {"state": "STOPPED", "active_instances": 0}
        elif path.endswith("pipelines/pipe/stop"):
            self.pipelines[0]["state"] = "IDLE"
        elif method == "PUT" and path.endswith("pipelines/pipe"):
            self.pipelines[0]["spec"] = deepcopy(body)
        else:
            raise AssertionError((method, path, query, body))
        return {}


class PauseTests(unittest.TestCase):
    def test_dry_run_has_no_writes_and_reads_every_page(self):
        client = Workspace()
        result = pause_workspace(client, emit=lambda _: None)
        self.assertEqual(result["counts"]["jobs"], 2)
        self.assertTrue(all(method == "GET" for method, _, _ in client.calls))
        self.assertTrue(result["changes_required"])

    def test_live_preserves_self_and_configuration_and_verifies(self):
        client = Workspace()
        result = pause_workspace(client, run_live=True, current_run_id=10, emit=lambda _: None)
        self.assertTrue(result["verified"])
        self.assertEqual(client.runs, [{"run_id": 10, "job_id": 1}])
        self.assertEqual(client.jobs[0]["settings"]["schedule"]["timezone_id"], "UTC")
        self.assertEqual(client.jobs[1]["settings"]["trigger"]["file_arrival"], {"url": "/Volumes/x"})
        self.assertFalse(client.pipelines[0]["spec"]["continuous"])
        self.assertEqual(client.pipelines[0]["spec"]["trigger"], {"manual": {}})
        self.assertEqual(client.pipelines[0]["spec"]["libraries"], [{"file": {"path": "/x.py"}}])
        self.assertEqual(client.pipelines[0]["spec"]["expected_last_modified"], 123)
        canceled = [body for _, path, body in client.calls if path.endswith("cancel-all")]
        self.assertEqual(canceled, [{"job_id": 2, "all_queued_runs": True}])
        # Automation is disabled before cancellation, and self is never canceled.
        self.assertLess(next(i for i, c in enumerate(client.calls) if c[0] == "PUT"), next(i for i, c in enumerate(client.calls) if c[1].endswith("runs/cancel")))

    def test_failure_does_not_prevent_stopping_other_resources(self):
        client = Workspace()
        client.fail_stop = True
        with self.assertRaises(PauseError) as raised:
            pause_workspace(client, run_live=True, timeout_seconds=0.0001, poll_seconds=0, emit=lambda _: None)
        self.assertIn("Denied", str(raised.exception))
        self.assertEqual(client.pipelines[0]["state"], "IDLE")

    def test_managed_pipeline_stops_without_unsupported_edit(self):
        client = Workspace()
        client.pipelines[0]["spec"].pop("trigger")
        client.pipelines[0]["spec"]["pipeline_type"] = "DATABASE_TABLE_SYNC"
        client.pipelines[0]["spec"]["managed_definition"] = {"database_table_sync": {}}
        result = pause_workspace(client, run_live=True, emit=lambda _: None)
        self.assertTrue(result["verified"])
        self.assertEqual(client.pipelines[0]["state"], "IDLE")
        self.assertFalse(any(method == "PUT" for method, _, _ in client.calls))
        self.assertEqual(result["managed_pipeline_modes_retained"], [{"pipeline_id": "pipe", "continuous": True}])

    def test_run_promoted_during_bulk_cancellation_is_canceled_individually(self):
        client = Workspace()
        original_do = client.do
        injected = False

        def do(method, path, query=None, body=None):
            nonlocal injected
            result = original_do(method, path, query=query, body=body)
            if path.endswith("runs/cancel-all") and not injected:
                client.runs.append({"run_id": 99, "job_id": 1, "state": {"life_cycle_state": "RUNNING"}})
                injected = True
            return result

        client.do = do
        result = pause_workspace(client, run_live=True, poll_seconds=0, emit=lambda _: None)
        self.assertTrue(result["verified"])
        self.assertFalse(client.runs)
        self.assertTrue(any(path.endswith("runs/cancel") and body == {"run_id": 99}
                            for _, path, body in client.calls))

    def test_pipeline_spec_copy_does_not_mutate_snapshot(self):
        original = {"continuous": True, "configuration": {"a": "b"}}
        changed = paused_pipeline_spec(original)
        self.assertTrue(original["continuous"])
        self.assertFalse(changed["continuous"])


if __name__ == "__main__":
    unittest.main()
