"""Pure helpers for copying one Unity Catalog schema into many schemas."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

TABLE_TYPES = {"BASE TABLE", "EXTERNAL", "MANAGED"}
VIEW_TYPE = "VIEW"
SQL_IDENTIFIER = r"(?:`(?:``|[^`])*`|[A-Za-z_][A-Za-z0-9_$]*)"
VIEW_HEADER = re.compile(
    rf"(?is)^(?P<leading>\s*)CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+"
    rf"(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>{SQL_IDENTIFIER}"
    rf"(?:\s*\.\s*{SQL_IDENTIFIER}){{0,2}})"
)


def quote_identifier(identifier: str) -> str:
    """Backtick-quote a Unity Catalog identifier."""
    return "`" + identifier.replace("`", "``") + "`"


def quote_string(value: str) -> str:
    """Quote a SQL string literal."""
    return "'" + value.replace("'", "''") + "'"


def parse_boolean(value: str, parameter_name: str) -> bool:
    """Parse a required true/false job parameter."""
    normalized = value.strip().casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"{parameter_name} must be 'true' or 'false'; got {value!r}")


def parse_schema_list(value: str) -> set[str]:
    """Parse a comma-separated schema list into case-insensitive keys."""
    return {part.strip().casefold() for part in value.split(",") if part.strip()}


def select_destination_schemas(
    schemas: Iterable[str],
    *,
    source_catalog: str,
    source_schema: str,
    destination_catalog: str,
    excluded_schemas: Iterable[str] = (),
) -> list[str]:
    """Select writable destination schemas, preserving their catalog spelling."""
    excluded = {schema.casefold() for schema in excluded_schemas}
    excluded.add("information_schema")
    if source_catalog.casefold() == destination_catalog.casefold():
        excluded.add(source_schema.casefold())

    selected_by_key: dict[str, str] = {}
    for schema in schemas:
        key = schema.casefold()
        if key not in excluded:
            selected_by_key.setdefault(key, schema)
    return sorted(selected_by_key.values(), key=str.casefold)


def object_kind(table_type: str) -> str | None:
    """Map an information_schema table type to a supported object kind."""
    normalized = table_type.strip().upper()
    if normalized in TABLE_TYPES:
        return "table"
    if normalized == VIEW_TYPE:
        return "view"
    return None


def qualified_name(catalog: str, schema: str, object_name: str) -> str:
    """Return a safely quoted three-part Unity Catalog name."""
    return ".".join(quote_identifier(part) for part in (catalog, schema, object_name))


def build_clone_statement(
    *,
    source_catalog: str,
    source_schema: str,
    destination_catalog: str,
    destination_schema: str,
    table_name: str,
    overwrite_existing: bool,
) -> str:
    """Build a DEEP CLONE statement for a source and destination table."""
    create = "CREATE OR REPLACE TABLE" if overwrite_existing else "CREATE TABLE"
    source = qualified_name(source_catalog, source_schema, table_name)
    destination = qualified_name(destination_catalog, destination_schema, table_name)
    return f"{create} {destination} DEEP CLONE {source}"


def build_drop_statement(
    *,
    catalog: str,
    schema: str,
    object_name: str,
    object_type: str,
) -> str:
    """Build a DROP statement for a supported conflicting object."""
    kind = object_kind(object_type)
    if kind is None:
        raise ValueError(f"Cannot replace unsupported object type {object_type!r}")
    return f"DROP {kind.upper()} {qualified_name(catalog, schema, object_name)}"


def rewrite_view_ddl(
    ddl: str,
    *,
    source_catalog: str,
    source_schema: str,
    destination_catalog: str,
    destination_schema: str,
    view_name: str,
    overwrite_existing: bool,
) -> str:
    """Retarget a SHOW CREATE TABLE view DDL to a destination schema.

    SHOW CREATE emits fully qualified, backtick-quoted object names. Replacing
    only the quoted source-schema prefix retargets same-schema dependencies but
    deliberately leaves references to other schemas and catalogs unchanged.
    """
    source_prefix = ".".join(
        quote_identifier(part) for part in (source_catalog, source_schema)
    )
    destination_prefix = ".".join(
        quote_identifier(part) for part in (destination_catalog, destination_schema)
    )
    match = VIEW_HEADER.match(ddl)
    if match is None:
        raise ValueError(f"SHOW CREATE output for {view_name!r} is not a view DDL")

    header_identifiers = re.findall(
        r"`((?:``|[^`])*)`|([A-Za-z_][A-Za-z0-9_$]*)", match.group("name")
    )
    header_view_name = next(part for part in header_identifiers[-1] if part)
    header_view_name = header_view_name.replace("``", "`")
    if header_view_name.casefold() != view_name.casefold():
        raise ValueError(
            f"SHOW CREATE output named view {header_view_name!r}; expected {view_name!r}"
        )

    create = "CREATE OR REPLACE VIEW" if overwrite_existing else "CREATE VIEW"
    destination_view = f"{destination_prefix}.{quote_identifier(view_name)}"
    tail = ddl[match.end() :].replace(f"{source_prefix}.", f"{destination_prefix}.")
    return f"{match.group('leading')}{create} {destination_view}{tail}"


def find_view_dependencies(
    ddl: str,
    *,
    source_catalog: str,
    source_schema: str,
    view_name: str,
    candidate_views: Iterable[str],
) -> set[str]:
    """Find fully qualified same-schema view references in SHOW CREATE DDL."""
    current_key = view_name.casefold()
    return {
        candidate
        for candidate in candidate_views
        if candidate.casefold() != current_key
        and qualified_name(source_catalog, source_schema, candidate) in ddl
    }


def order_views(
    view_names: Iterable[str], dependencies: Mapping[str, Iterable[str]]
) -> list[str]:
    """Topologically order views by same-schema view dependencies."""
    names_by_key: dict[str, str] = {}
    for name in view_names:
        key = name.casefold()
        if key in names_by_key and names_by_key[key] != name:
            raise ValueError(
                f"View names differ only by case: {names_by_key[key]!r}, {name!r}"
            )
        names_by_key[key] = name

    remaining: dict[str, set[str]] = {}
    for key, name in names_by_key.items():
        remaining[key] = {
            dependency.casefold()
            for dependency in dependencies.get(name, ())
            if dependency.casefold() in names_by_key
        }

    ordered: list[str] = []
    while remaining:
        ready = sorted(
            (key for key, required in remaining.items() if not required),
            key=lambda key: names_by_key[key].casefold(),
        )
        if not ready:
            cycle = ", ".join(
                sorted((names_by_key[key] for key in remaining), key=str.casefold)
            )
            raise ValueError(f"View dependency cycle detected among: {cycle}")
        for key in ready:
            ordered.append(names_by_key[key])
            del remaining[key]
        for required in remaining.values():
            required.difference_update(ready)
    return ordered
