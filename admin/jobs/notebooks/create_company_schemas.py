# Databricks notebook source
# ruff: noqa: F821
"""Create a Unity Catalog schema per company and grant the company group access."""

# COMMAND ----------

import csv
import re
from pathlib import Path

# COMMAND ----------

dbutils.widgets.text("catalog", "databricks-hackathon")
dbutils.widgets.text(
    "csv_path", "/Volumes/admin/workshop_provisioning/user_provisioning/users.csv"
)
dbutils.widgets.text("schema_owner_group", "workshop_admins")
dbutils.widgets.dropdown("run_live", "false", ["false", "true"])

catalog = dbutils.widgets.get("catalog").strip()
csv_path = dbutils.widgets.get("csv_path").strip()
schema_owner_group = dbutils.widgets.get("schema_owner_group").strip()
run_live = dbutils.widgets.get("run_live").strip().lower() == "true"

if not all([catalog, csv_path, schema_owner_group]):
    raise ValueError("catalog, csv_path, and schema_owner_group parameters are required")

# COMMAND ----------

EXPECTED_HEADERS = {"email_address", "company"}
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ACCOUNT_USERS_GROUP = "account users"


def load_companies(path: str) -> dict[str, str]:
    """Return distinct companies from the CSV, keyed by casefold, value is the
    first-seen original string (which is also the account group display name)."""
    with Path(path).open(newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        headers = set(reader.fieldnames or [])
        if headers != EXPECTED_HEADERS:
            raise ValueError(
                f"CSV headers must be exactly {sorted(EXPECTED_HEADERS)}; got {sorted(headers)}"
            )

        companies: dict[str, str] = {}
        for line_number, raw_row in enumerate(reader, start=2):
            email = (raw_row.get("email_address") or "").strip().lower()
            company = (raw_row.get("company") or "").strip()
            if not EMAIL_PATTERN.fullmatch(email):
                raise ValueError(
                    f"Invalid email_address on CSV line {line_number}: {email!r}"
                )
            if not company:
                raise ValueError(f"company is required on CSV line {line_number}")
            companies.setdefault(company.casefold(), company)

    if not companies:
        raise ValueError("CSV must contain at least one company")
    return companies


def sanitize_schema_name(company: str) -> str:
    """Normalize a company name into a valid unquoted schema identifier."""
    name = re.sub(r"[^0-9a-z]+", "_", company.casefold()).strip("_")
    if not name:
        raise ValueError(f"Company {company!r} has no usable schema name characters")
    return name


def quote_identifier(identifier: str) -> str:
    """Backtick-quote an identifier, escaping embedded backticks."""
    return "`" + identifier.replace("`", "``") + "`"


# COMMAND ----------

companies = load_companies(csv_path)

# Map each distinct company to its sanitized schema name, failing loudly if two
# different company strings would collapse into the same schema.
schema_by_company: dict[str, str] = {}
schema_to_company: dict[str, str] = {}
for company in companies.values():
    schema = sanitize_schema_name(company)
    existing = schema_to_company.get(schema)
    if existing is not None and existing != company:
        raise ValueError(
            f"Companies {existing!r} and {company!r} both map to schema {schema!r}; "
            "resolve the naming collision in the CSV"
        )
    schema_by_company[company] = schema
    schema_to_company[schema] = company

mode = "LIVE" if run_live else "DRY RUN"
print(f"Mode: {mode}")
print(f"Catalog: {catalog}")
print(f"Schema owner group: {schema_owner_group}")
print(f"Distinct companies: {len(schema_by_company)}")

# COMMAND ----------

catalog_ident = quote_identifier(catalog)
owner_ident = quote_identifier(schema_owner_group)
account_users_ident = quote_identifier(ACCOUNT_USERS_GROUP)

# Every account user inherits privileges granted to `account users`. Keep that
# principal at USE CATALOG only so company users can traverse this catalog but
# cannot discover or access every schema through an inherited catalog-level
# grant. The run-as identity must own the catalog or have MANAGE on it.
catalog_isolation_statements = [
    f"REVOKE ALL PRIVILEGES ON CATALOG {catalog_ident} FROM {account_users_ident}",
    (
        "REVOKE BROWSE, MANAGE, READ METADATA ON CATALOG "
        f"{catalog_ident} FROM {account_users_ident}"
    ),
    f"GRANT USE CATALOG ON CATALOG {catalog_ident} TO {account_users_ident}",
]

print(f"\nRestricting {ACCOUNT_USERS_GROUP!r} to catalog traversal only")
for statement in catalog_isolation_statements:
    if run_live:
        print(f"  run: {statement}")
        spark.sql(statement)
    else:
        print(f"  would run: {statement}")

for company, schema in schema_by_company.items():
    schema_ident = f"{catalog_ident}.{quote_identifier(schema)}"
    # The account group add_users created uses the company string as its
    # display name, so it is the grant principal here.
    group_ident = quote_identifier(company)

    # Remove any direct catalog-level grants from a reused company group, then
    # restore only USE CATALOG. Without BROWSE or other catalog-level
    # privileges, the group can discover only schemas on which it has a direct
    # privilege. The namesake schema receives both ALL PRIVILEGES and MANAGE;
    # MANAGE must be explicit because Unity Catalog excludes it from
    # ALL PRIVILEGES. Ownership is then transferred to a stable admin group.
    statements = [
        f"REVOKE ALL PRIVILEGES ON CATALOG {catalog_ident} FROM {group_ident}",
        (
            "REVOKE BROWSE, MANAGE, READ METADATA ON CATALOG "
            f"{catalog_ident} FROM {group_ident}"
        ),
        f"GRANT USE CATALOG ON CATALOG {catalog_ident} TO {group_ident}",
        f"CREATE SCHEMA IF NOT EXISTS {schema_ident}",
        f"GRANT ALL PRIVILEGES ON SCHEMA {schema_ident} TO {group_ident}",
        f"GRANT MANAGE ON SCHEMA {schema_ident} TO {group_ident}",
        f"ALTER SCHEMA {schema_ident} OWNER TO {owner_ident}",
    ]

    print(f"\n{company} | schema={catalog}.{schema}")
    for statement in statements:
        if run_live:
            print(f"  run: {statement}")
            spark.sql(statement)
        else:
            print(f"  would run: {statement}")

print(
    "\nSchema provisioning complete."
    if run_live
    else "\nDry run complete. No schemas or grants were changed."
)
