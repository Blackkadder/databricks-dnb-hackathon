# Databricks notebook source
"""Stop apps, pause jobs, and stop pipeline updates in this workspace."""

# COMMAND ----------

from databricks.sdk import WorkspaceClient
from workspace_pause import pause_workspace
import json

# COMMAND ----------

dbutils.widgets.dropdown("run_live", "false", ["false", "true"])
dbutils.widgets.text("current_run_id", "")
dbutils.widgets.text("timeout_seconds", "1200")

run_live_text = dbutils.widgets.get("run_live").strip().lower()
if run_live_text not in ("true", "false"):
    raise ValueError("run_live must be true or false")
current_run_id = dbutils.widgets.get("current_run_id").strip() or None
if current_run_id and not current_run_id.isdigit():
    raise ValueError("current_run_id must be the numeric job run ID")

result = pause_workspace(
    WorkspaceClient(),
    run_live=run_live_text == "true",
    current_run_id=current_run_id,
    timeout_seconds=int(dbutils.widgets.get("timeout_seconds")),
)
dbutils.notebook.exit(json.dumps(result))
