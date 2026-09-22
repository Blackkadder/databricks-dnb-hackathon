# Databricks notebook source
# ruff: noqa: F821
"""Copy Delta tables and retarget views from one schema to every destination."""

# COMMAND ----------

from schema_data_copy import (
    build_clone_statement,
    build_drop_statement,
    find_view_dependencies,
    object_kind,
    order_views,
    parse_boolean,
    parse_schema_list,
    qualified_name,
    quote_identifier,
    quote_string,
    rewrite_view_ddl,
    select_destination_schemas,
)

# COMMAND ----------

dbutils.widgets.text("source_catalog", "databricks-hackathon")
dbutils.widgets.text("source_schema", "00data")
dbutils.widgets.text("destination_catalog", "databricks-hackathon")
dbutils.widgets.text("excluded_destination_schemas", "information_schema")
dbutils.widgets.dropdown("overwrite_existing", "false", ["false", "true"])
dbutils.widgets.dropdown("run_live", "false", ["false", "true"])

source_catalog = dbutils.widgets.get("source_catalog").strip()
source_schema = dbutils.widgets.get("source_schema").strip()
destination_catalog = dbutils.widgets.get("destination_catalog").strip()
excluded_destination_schemas = parse_schema_list(
    dbutils.widgets.get("excluded_destination_schemas")
)
overwrite_existing = parse_boolean(
    dbutils.widgets.get("overwrite_existing"), "overwrite_existing"
)
run_live = parse_boolean(dbutils.widgets.get("run_live"), "run_live")

if not all([source_catalog, source_schema, destination_catalog]):
    raise ValueError(
        "source_catalog, source_schema, and destination_catalog are required"
    )

# COMMAND ----------


def list_schemas(catalog: str) -> list[str]:
    """List schema names using the catalog's canonical spelling."""
    rows = spark.sql(f"SHOW SCHEMAS IN {quote_identifier(catalog)}").collect()
    return [str(row[0]) for row in rows]


def canonical_name(name: str, available_names: list[str]) -> str | None:
    """Resolve a Unity Catalog name case-insensitively."""
    requested = name.casefold()
    return next(
        (
            candidate
            for candidate in available_names
            if candidate.casefold() == requested
        ),
        None,
    )


def describe_list(values: list[str], limit: int = 30) -> str:
    """Format a bounded list for validation errors."""
    displayed = values[:limit]
    suffix = f" ... and {len(values) - limit} more" if len(values) > limit else ""
    return ", ".join(displayed) + suffix


# Resolve catalogs and schemas before building a plan. This both preserves the
# canonical spelling used by SHOW CREATE and fails early on inaccessible input.
available_catalogs = [str(row[0]) for row in spark.sql("SHOW CATALOGS").collect()]
resolved_source_catalog = canonical_name(source_catalog, available_catalogs)
resolved_destination_catalog = canonical_name(destination_catalog, available_catalogs)
if resolved_source_catalog is None:
    raise ValueError(
        f"Source catalog {source_catalog!r} does not exist or is inaccessible"
    )
if resolved_destination_catalog is None:
    raise ValueError(
        f"Destination catalog {destination_catalog!r} does not exist or is inaccessible"
    )
source_catalog = resolved_source_catalog
destination_catalog = resolved_destination_catalog

source_schemas = list_schemas(source_catalog)
resolved_source_schema = canonical_name(source_schema, source_schemas)
if resolved_source_schema is None:
    raise ValueError(
        f"Source schema {source_catalog}.{source_schema} does not exist or is inaccessible"
    )
source_schema = resolved_source_schema

available_destination_schemas = list_schemas(destination_catalog)
destination_schemas = select_destination_schemas(
    available_destination_schemas,
    source_catalog=source_catalog,
    source_schema=source_schema,
    destination_catalog=destination_catalog,
    excluded_schemas=excluded_destination_schemas,
)
if not destination_schemas:
    raise ValueError("No writable destination schemas remain after exclusions")

# COMMAND ----------

# Discover all persistent source relations. Only Delta tables and regular views
# are supported: DEEP CLONE preserves Delta metadata and creates independent
# data files, while SHOW CREATE preserves each view's authored definition.
source_objects = spark.sql(
    f"""
    SELECT table_name, table_type, data_source_format
    FROM {quote_identifier(source_catalog)}.information_schema.tables
    WHERE lower(table_schema) = lower({quote_string(source_schema)})
    ORDER BY lower(table_name)
    """
).collect()

tables: list[str] = []
views: list[str] = []
unsupported_source_objects: list[str] = []
source_kind_by_name: dict[str, str] = {}
for row in source_objects:
    table_name = str(row["table_name"])
    table_type = str(row["table_type"])
    data_source_format = row["data_source_format"]
    kind = object_kind(table_type)
    if kind == "table" and str(data_source_format or "").casefold() == "delta":
        tables.append(table_name)
        source_kind_by_name[table_name.casefold()] = "table"
    elif kind == "view":
        views.append(table_name)
        source_kind_by_name[table_name.casefold()] = "view"
    else:
        detail = table_type
        if data_source_format:
            detail += f"/{data_source_format}"
        unsupported_source_objects.append(f"{table_name} ({detail})")

if unsupported_source_objects:
    raise ValueError(
        "Source schema contains unsupported objects; only Delta tables and regular "
        f"views can be copied: {describe_list(unsupported_source_objects)}"
    )
if not tables and not views:
    raise ValueError(
        f"Source schema {source_catalog}.{source_schema} contains no tables or views"
    )

# SHOW CREATE is supported more broadly than information_schema dependency
# relations. It also provides the canonical DDL needed to recreate each view.
source_view_ddl: dict[str, str] = {}
for view_name in views:
    rows = spark.sql(
        f"SHOW CREATE TABLE {qualified_name(source_catalog, source_schema, view_name)}"
    ).collect()
    if not rows:
        raise ValueError(f"SHOW CREATE returned no DDL for source view {view_name!r}")
    source_view_ddl[view_name] = "\n".join(str(row[0]) for row in rows)

dependencies = {
    view_name: find_view_dependencies(
        source_view_ddl[view_name],
        source_catalog=source_catalog,
        source_schema=source_schema,
        view_name=view_name,
        candidate_views=views,
    )
    for view_name in views
}
ordered_views = order_views(views, dependencies)

# COMMAND ----------

# Catalog-wide information_schema access lets the job identify every collision
# before the first write. This prevents avoidable partial copies.
destination_keys = {schema.casefold() for schema in destination_schemas}
source_names = set(source_kind_by_name)
destination_schema_by_key = {
    schema.casefold(): schema for schema in destination_schemas
}
source_name_by_key = {name.casefold(): name for name in tables + views}
existing_by_target: dict[tuple[str, str], str] = {}
destination_objects = spark.sql(
    f"""
    SELECT table_schema, table_name, table_type
    FROM {quote_identifier(destination_catalog)}.information_schema.tables
    """
).collect()
for row in destination_objects:
    schema_key = str(row["table_schema"]).casefold()
    object_key = str(row["table_name"]).casefold()
    if schema_key in destination_keys and object_key in source_names:
        existing_by_target[(schema_key, object_key)] = str(row["table_type"])

conflicts = sorted(
    (
        f"{destination_schema_by_key[schema_key]}."
        f"{source_name_by_key[name_key]} ({table_type})"
        for (schema_key, name_key), table_type in existing_by_target.items()
    ),
    key=str.casefold,
)
if conflicts and not overwrite_existing:
    raise ValueError(
        "Destination objects already exist. Review them and rerun with "
        "overwrite_existing=true to replace them: " + describe_list(conflicts)
    )

# Replacing an object with a different kind requires an explicit DROP. Reject
# specialized target relations rather than guessing at destructive syntax.
drop_by_target: dict[tuple[str, str], str] = {}
if overwrite_existing:
    unsupported_target_conflicts: list[str] = []
    for (schema_key, object_key), existing_type in existing_by_target.items():
        existing_kind = object_kind(existing_type)
        desired_kind = source_kind_by_name[object_key]
        if existing_kind is None:
            unsupported_target_conflicts.append(
                f"{schema_key}.{object_key} ({existing_type})"
            )
        elif existing_kind != desired_kind:
            drop_by_target[(schema_key, object_key)] = build_drop_statement(
                catalog=destination_catalog,
                schema=destination_schema_by_key[schema_key],
                object_name=source_name_by_key[object_key],
                object_type=existing_type,
            )
    if unsupported_target_conflicts:
        raise ValueError(
            "Cannot overwrite specialized destination objects: "
            + describe_list(sorted(unsupported_target_conflicts))
        )

# COMMAND ----------

mode = "LIVE" if run_live else "DRY RUN"
print(f"Mode: {mode}")
print(f"Source: {source_catalog}.{source_schema}")
print(f"Destination catalog: {destination_catalog}")
print(f"Overwrite existing objects: {overwrite_existing}")
print(f"Source Delta tables: {len(tables)}")
print(f"Source views: {len(ordered_views)}")
print(f"Destination schemas: {len(destination_schemas)}")
effective_exclusions = excluded_destination_schemas | {"information_schema"}
if source_catalog.casefold() == destination_catalog.casefold():
    effective_exclusions.add(source_schema.casefold())
print(f"Excluded destination schemas: {', '.join(sorted(effective_exclusions))}")
print(
    "Planned object copies: "
    f"{(len(tables) + len(ordered_views)) * len(destination_schemas)}"
)

completed: list[str] = []
for destination_schema in destination_schemas:
    print(f"\nDestination: {destination_catalog}.{destination_schema}")

    for table_name in tables:
        target_key = (destination_schema.casefold(), table_name.casefold())
        drop_statement = drop_by_target.get(target_key)
        clone_statement = build_clone_statement(
            source_catalog=source_catalog,
            source_schema=source_schema,
            destination_catalog=destination_catalog,
            destination_schema=destination_schema,
            table_name=table_name,
            overwrite_existing=overwrite_existing,
        )
        if drop_statement:
            print(f"  {'run' if run_live else 'would run'}: {drop_statement}")
            if run_live:
                spark.sql(drop_statement)
        print(f"  {'run' if run_live else 'would run'}: {clone_statement}")
        if run_live:
            spark.sql(clone_statement)
            completed.append(f"{destination_schema}.{table_name}")

    if ordered_views and run_live:
        # Unqualified references in a source view should bind to objects in the
        # destination schema. Fully qualified same-schema references are also
        # rewritten below.
        spark.sql(f"USE CATALOG {quote_identifier(destination_catalog)}")
        spark.sql(f"USE SCHEMA {quote_identifier(destination_schema)}")

    for view_name in ordered_views:
        target_key = (destination_schema.casefold(), view_name.casefold())
        drop_statement = drop_by_target.get(target_key)
        view_statement = rewrite_view_ddl(
            source_view_ddl[view_name],
            source_catalog=source_catalog,
            source_schema=source_schema,
            destination_catalog=destination_catalog,
            destination_schema=destination_schema,
            view_name=view_name,
            overwrite_existing=overwrite_existing,
        )
        if drop_statement:
            print(f"  {'run' if run_live else 'would run'}: {drop_statement}")
            if run_live:
                spark.sql(drop_statement)
        print(f"  {'run' if run_live else 'would run'} view: {view_name}")
        if not run_live:
            print(view_statement)
        else:
            spark.sql(view_statement)
            completed.append(f"{destination_schema}.{view_name}")

if run_live:
    print(f"\nCopy complete. Created or replaced {len(completed)} objects.")
else:
    print("\nDry run complete. No tables or views were changed.")
