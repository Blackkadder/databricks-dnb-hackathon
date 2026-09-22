import sys
import unittest
from pathlib import Path

NOTEBOOKS_DIR = Path(__file__).parent / "notebooks"
sys.path.insert(0, str(NOTEBOOKS_DIR))

from schema_data_copy import (
    build_clone_statement,
    build_drop_statement,
    find_view_dependencies,
    order_views,
    parse_boolean,
    parse_schema_list,
    quote_identifier,
    rewrite_view_ddl,
    select_destination_schemas,
)


class SchemaDataCopyTest(unittest.TestCase):
    def test_quotes_identifiers_and_clone_statement(self) -> None:
        self.assertEqual(quote_identifier("team`one"), "`team``one`")
        self.assertEqual(
            build_clone_statement(
                source_catalog="source-catalog",
                source_schema="seed",
                destination_catalog="destination-catalog",
                destination_schema="Team One",
                table_name="orders",
                overwrite_existing=True,
            ),
            "CREATE OR REPLACE TABLE "
            "`destination-catalog`.`Team One`.`orders` DEEP CLONE "
            "`source-catalog`.`seed`.`orders`",
        )

    def test_selects_destinations_and_applies_mandatory_exclusions(self) -> None:
        selected = select_destination_schemas(
            ["00data", "information_schema", "Team_One", "TEAM_TWO", "admin"],
            source_catalog="databricks-hackathon",
            source_schema="00DATA",
            destination_catalog="DATABRICKS-HACKATHON",
            excluded_schemas={"Admin"},
        )
        self.assertEqual(selected, ["Team_One", "TEAM_TWO"])

    def test_same_schema_name_is_allowed_in_a_different_catalog(self) -> None:
        selected = select_destination_schemas(
            ["00data", "information_schema"],
            source_catalog="source",
            source_schema="00data",
            destination_catalog="destination",
        )
        self.assertEqual(selected, ["00data"])

    def test_rewrites_view_and_preserves_external_references(self) -> None:
        ddl = """CREATE VIEW `databricks-hackathon`.`00data`.`customer_360`
AS SELECT c.*
FROM `databricks-hackathon`.`00data`.`customers` AS c
JOIN `reference`.`shared`.`countries` AS r USING (country_code)"""
        rewritten = rewrite_view_ddl(
            ddl,
            source_catalog="databricks-hackathon",
            source_schema="00data",
            destination_catalog="databricks-hackathon",
            destination_schema="team_one",
            view_name="customer_360",
            overwrite_existing=True,
        )
        self.assertTrue(rewritten.startswith("CREATE OR REPLACE VIEW"))
        self.assertIn("`databricks-hackathon`.`team_one`.`customer_360`", rewritten)
        self.assertIn("`databricks-hackathon`.`team_one`.`customers`", rewritten)
        self.assertIn("`reference`.`shared`.`countries`", rewritten)
        self.assertNotIn("`databricks-hackathon`.`00data`", rewritten)

    def test_rewrites_unqualified_show_create_view_name(self) -> None:
        rewritten = rewrite_view_ddl(
            "CREATE VIEW `customer_360` AS "
            "SELECT * FROM `databricks-hackathon`.`00data`.`customers`",
            source_catalog="databricks-hackathon",
            source_schema="00data",
            destination_catalog="databricks-hackathon",
            destination_schema="team_one",
            view_name="customer_360",
            overwrite_existing=False,
        )
        self.assertEqual(
            rewritten,
            "CREATE VIEW `databricks-hackathon`.`team_one`.`customer_360` AS "
            "SELECT * FROM `databricks-hackathon`.`team_one`.`customers`",
        )

    def test_orders_dependent_views(self) -> None:
        self.assertEqual(
            order_views(
                ["customer_rollup", "customer_360", "base_view"],
                {
                    "customer_rollup": {"customer_360"},
                    "customer_360": {"base_view", "customers"},
                },
            ),
            ["base_view", "customer_360", "customer_rollup"],
        )

    def test_finds_fully_qualified_view_dependencies(self) -> None:
        ddl = """CREATE VIEW `catalog`.`seed`.`customer_rollup`
AS SELECT * FROM `catalog`.`seed`.`customer_360`
JOIN `reference`.`shared`.`countries` USING (country_code)"""
        self.assertEqual(
            find_view_dependencies(
                ddl,
                source_catalog="catalog",
                source_schema="seed",
                view_name="customer_rollup",
                candidate_views=["customer_rollup", "customer_360", "other_view"],
            ),
            {"customer_360"},
        )

    def test_rejects_view_dependency_cycle(self) -> None:
        with self.assertRaisesRegex(ValueError, "dependency cycle"):
            order_views(["one", "two"], {"one": {"two"}, "two": {"one"}})

    def test_parses_job_parameters(self) -> None:
        self.assertTrue(parse_boolean(" TRUE ", "run_live"))
        self.assertFalse(parse_boolean("false", "run_live"))
        self.assertEqual(
            parse_schema_list(" admin, Sandbox,admin "), {"admin", "sandbox"}
        )
        with self.assertRaisesRegex(ValueError, "must be 'true' or 'false'"):
            parse_boolean("yes", "run_live")

    def test_builds_drop_for_conflicting_kind(self) -> None:
        self.assertEqual(
            build_drop_statement(
                catalog="catalog",
                schema="team",
                object_name="customers",
                object_type="VIEW",
            ),
            "DROP VIEW `catalog`.`team`.`customers`",
        )


if __name__ == "__main__":
    unittest.main()
