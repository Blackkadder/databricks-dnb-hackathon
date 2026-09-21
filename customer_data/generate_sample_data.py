"""Generate the approved, linked retail sample in Unity Catalog.

Approved plan:
- Seed: 42; snapshot date: 2026-09-16
- Destination: databricks-hackathon.00data
- 50 customers, 40 products, 1,000 transactions, 2,500 transaction items,
  2,000 customer events, 50 feature snapshots, and 50 predictions
- Stable IDs and MERGE writes make retries idempotent without replacing tables.
"""

from __future__ import annotations

import argparse
import os
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import numpy as np
import polars as pl
from mimesis import Generic
from mimesis.locales import Locale


SEED = 42
AS_OF_DATE = date(2026, 9, 16)
AS_OF_TS = datetime(2026, 9, 16, 0, 0, 0)
GENERATED_AT = datetime(2026, 9, 16, 12, 0, 0)
SOURCE_SYSTEM = "sample_seed_42"

CUSTOMER_COUNT = 50
PRODUCT_COUNT = 40
TRANSACTION_COUNT = 1_000
TRANSACTION_ITEM_COUNT = 2_500
EVENT_COUNT = 2_000

MONEY_QUANTUM = Decimal("0.01")


def money(value: Any) -> Decimal:
    """Return a non-binary fixed-precision monetary value."""
    return Decimal(str(value)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def bounded(value: float, low: float = 0.01, high: float = 0.99) -> float:
    return round(float(np.clip(value, low, high)), 6)


def random_datetime(
    rng: np.random.Generator, start: datetime, end: datetime
) -> datetime:
    if start > end:
        start = end
    seconds = max(0, int((end - start).total_seconds()))
    return start + timedelta(seconds=int(rng.integers(0, seconds + 1)))


def quote_identifier(value: str) -> str:
    return f"`{value.replace('`', '``')}`"


def table_name(catalog: str, schema: str, table: str) -> str:
    return ".".join(map(quote_identifier, (catalog, schema, table)))


def build_customers(
    rng: np.random.Generator, generic: Generic
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    cohorts = (
        ["loyal"] * 10
        + ["active"] * 17
        + ["new"] * 8
        + ["at_risk"] * 10
        + ["dormant"] * 5
    )
    locations = [
        ("New York", "NY", "10001"),
        ("Los Angeles", "CA", "90001"),
        ("Chicago", "IL", "60601"),
        ("Houston", "TX", "77001"),
        ("Phoenix", "AZ", "85001"),
        ("Philadelphia", "PA", "19103"),
        ("Miami", "FL", "33101"),
        ("Columbus", "OH", "43004"),
        ("Charlotte", "NC", "28202"),
        ("Atlanta", "GA", "30301"),
    ]
    categories = ["Electronics", "Apparel", "Home", "Beauty", "Sports"]
    signup_ranges = {
        "loyal": (date(2019, 1, 1), date(2022, 12, 31)),
        "active": (date(2021, 1, 1), date(2025, 12, 31)),
        "new": (date(2026, 3, 1), date(2026, 8, 31)),
        "at_risk": (date(2020, 1, 1), date(2024, 12, 31)),
        "dormant": (date(2018, 1, 1), date(2022, 12, 31)),
    }
    tier_values = {
        "loyal": ["gold", "platinum"],
        "active": ["silver", "gold"],
        "new": ["none", "bronze"],
        "at_risk": ["bronze", "silver"],
        "dormant": ["none", "bronze"],
    }
    channels = ["web", "app", "store"]

    rows: list[dict[str, Any]] = []
    behavior: dict[str, dict[str, str]] = {}
    for index, cohort in enumerate(cohorts, start=1):
        customer_id = f"CUST-{index:04d}"
        first_name = generic.person.first_name()
        last_name = generic.person.last_name()
        slug = re.sub(r"[^a-z0-9]+", ".", f"{first_name}.{last_name}".lower()).strip(".")
        signup_start, signup_end = signup_ranges[cohort]
        signup_span = (signup_end - signup_start).days
        signup_date = signup_start + timedelta(days=int(rng.integers(0, signup_span + 1)))
        age_years = int(rng.integers(18, 76))
        date_of_birth = AS_OF_DATE - timedelta(
            days=age_years * 365 + int(rng.integers(0, 365))
        )
        city, state, postal_code = locations[(index - 1) % len(locations)]
        preferred_channel = str(rng.choice(channels, p=[0.48, 0.37, 0.15]))
        preferred_category = categories[(index - 1) % len(categories)]
        marketing_opt_in = bool(rng.random() < 0.82)
        if cohort == "dormant" and index % 2 == 0:
            account_status = "inactive"
        elif cohort == "at_risk" and index % 10 == 0:
            account_status = "suspended"
        else:
            account_status = "active"

        rows.append(
            {
                "customer_id": customer_id,
                "first_name": first_name,
                "last_name": last_name,
                "email": f"{slug}.{index:04d}@example.test",
                "phone": generic.person.telephone(),
                "date_of_birth": date_of_birth,
                "signup_date": signup_date,
                "segment": cohort,
                "loyalty_tier": str(rng.choice(tier_values[cohort])),
                "city": city,
                "state_province": state,
                "postal_code": postal_code,
                "country_code": "US",
                "preferred_channel": preferred_channel,
                "marketing_opt_in": marketing_opt_in,
                "account_status": account_status,
                "synthetic_record": True,
                "source_system": SOURCE_SYSTEM,
                "source_updated_at": GENERATED_AT,
            }
        )
        behavior[customer_id] = {
            "cohort": cohort,
            "preferred_channel": preferred_channel,
            "preferred_category": preferred_category,
        }

    return rows, behavior


def build_products(rng: np.random.Generator) -> list[dict[str, Any]]:
    taxonomy = {
        "Electronics": ["Headphones", "Speaker", "Keyboard", "Smartwatch"],
        "Apparel": ["Jacket", "Sneakers", "Shirt", "Backpack"],
        "Home": ["Lamp", "Cookware", "Bedding", "Storage"],
        "Beauty": ["Skincare", "Fragrance", "Haircare", "Makeup"],
        "Sports": ["Yoga", "Cycling", "Running", "Fitness"],
    }
    price_ranges = {
        "Electronics": (35, 450),
        "Apparel": (15, 180),
        "Home": (12, 260),
        "Beauty": (8, 140),
        "Sports": (10, 300),
    }
    brands = ["Northstar", "Aperture", "Willow", "Summit", "Harbor"]
    categories = list(taxonomy)
    rows: list[dict[str, Any]] = []
    for index in range(1, PRODUCT_COUNT + 1):
        category = categories[(index - 1) % len(categories)]
        subcategories = taxonomy[category]
        subcategory = subcategories[((index - 1) // len(categories)) % len(subcategories)]
        brand = brands[(index - 1) % len(brands)]
        low, high = price_ranges[category]
        list_price = money(rng.uniform(low, high))
        unit_cost = money(list_price * Decimal(str(rng.uniform(0.45, 0.70))))
        rows.append(
            {
                "product_id": f"PROD-{index:03d}",
                "product_name": f"{brand} {subcategory} {index:02d}",
                "category": category,
                "subcategory": subcategory,
                "brand": brand,
                "unit_cost": unit_cost,
                "list_price": list_price,
                "active_flag": index <= 38,
                "source_system": SOURCE_SYSTEM,
            }
        )
    return rows


def activity_window(cohort: str, signup_date: date) -> tuple[datetime, datetime]:
    offsets = {
        "loyal": (180, 1),
        "active": (365, 1),
        "new": (200, 1),
        "at_risk": (540, 120),
        "dormant": (900, 365),
    }
    start_days, end_days = offsets[cohort]
    start = max(
        datetime.combine(signup_date, datetime.min.time()),
        AS_OF_TS - timedelta(days=start_days),
    )
    end = AS_OF_TS - timedelta(days=end_days)
    return start, max(start, end)


def build_transactions_and_items(
    rng: np.random.Generator,
    customers: list[dict[str, Any]],
    behavior: dict[str, dict[str, str]],
    products: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    customer_lookup = {row["customer_id"]: row for row in customers}
    customer_ids = list(customer_lookup)
    cohort_weights = {
        "loyal": 3.0,
        "active": 2.5,
        "new": 1.3,
        "at_risk": 1.0,
        "dormant": 0.4,
    }
    weights = np.array(
        [cohort_weights[behavior[customer_id]["cohort"]] for customer_id in customer_ids]
    )
    weights = weights / weights.sum()
    assigned_customers = customer_ids + list(
        rng.choice(customer_ids, size=TRANSACTION_COUNT - CUSTOMER_COUNT, p=weights)
    )
    rng.shuffle(assigned_customers)

    products_by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for product in products:
        products_by_category[product["category"]].append(product)

    transactions: list[dict[str, Any]] = []
    transaction_items: list[dict[str, Any]] = []
    seen_customers: set[str] = set()
    status_values = ["completed", "pending", "cancelled", "refunded"]
    status_weights = [0.92, 0.03, 0.03, 0.02]
    payment_values = ["credit_card", "debit_card", "digital_wallet", "cash", "gift_card"]
    payment_weights = [0.42, 0.25, 0.20, 0.08, 0.05]

    for txn_index, customer_id in enumerate(assigned_customers, start=1):
        customer = customer_lookup[customer_id]
        profile = behavior[customer_id]
        start, end = activity_window(profile["cohort"], customer["signup_date"])
        transaction_ts = random_datetime(rng, start, end)
        if rng.random() < 0.70:
            channel = profile["preferred_channel"]
        else:
            channel = str(rng.choice(["web", "app", "store"]))
        status = str(rng.choice(status_values, p=status_weights))
        if customer_id not in seen_customers:
            status = "completed"
            seen_customers.add(customer_id)

        transaction_id = f"TXN-{txn_index:06d}"
        line_count = 2 if txn_index <= 500 else 3
        subtotal = money(0)
        total_discount = money(0)

        for line_number in range(1, line_count + 1):
            if rng.random() < 0.65:
                product_pool = products_by_category[profile["preferred_category"]]
            else:
                product_pool = products
            product = product_pool[int(rng.integers(0, len(product_pool)))]
            quantity = int(rng.choice([1, 2, 3, 4], p=[0.70, 0.20, 0.08, 0.02]))
            unit_price = product["list_price"]
            gross_amount = money(unit_price * quantity)
            discount_rate = Decimal(
                str(rng.choice([0.00, 0.05, 0.10, 0.15], p=[0.65, 0.20, 0.10, 0.05]))
            )
            discount_amount = money(gross_amount * discount_rate)
            line_amount = money(gross_amount - discount_amount)
            subtotal += gross_amount
            total_discount += discount_amount
            transaction_items.append(
                {
                    "transaction_id": transaction_id,
                    "line_number": line_number,
                    "product_id": product["product_id"],
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "discount_amount": discount_amount,
                    "line_amount": line_amount,
                }
            )

        tax_amount = money((subtotal - total_discount) * Decimal("0.08"))
        total_amount = money(subtotal - total_discount + tax_amount)
        transactions.append(
            {
                "transaction_id": transaction_id,
                "customer_id": customer_id,
                "transaction_ts": transaction_ts,
                "channel": channel,
                "store_id": f"STORE-{int(rng.integers(1, 11)):03d}" if channel == "store" else None,
                "currency_code": "USD",
                "subtotal_amount": subtotal,
                "discount_amount": total_discount,
                "tax_amount": tax_amount,
                "total_amount": total_amount,
                "payment_method": str(rng.choice(payment_values, p=payment_weights)),
                "transaction_status": status,
                "source_system": SOURCE_SYSTEM,
            }
        )

    return transactions, transaction_items


def build_events(
    rng: np.random.Generator,
    customers: list[dict[str, Any]],
    behavior: dict[str, dict[str, str]],
    products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    customer_lookup = {row["customer_id"]: row for row in customers}
    customer_ids = list(customer_lookup)
    cohort_weights = {"loyal": 3.0, "active": 2.6, "new": 1.8, "at_risk": 0.9, "dormant": 0.3}
    weights = np.array(
        [cohort_weights[behavior[customer_id]["cohort"]] for customer_id in customer_ids]
    )
    weights = weights / weights.sum()
    assigned_customers = customer_ids + list(
        rng.choice(customer_ids, size=EVENT_COUNT - CUSTOMER_COUNT, p=weights)
    )
    rng.shuffle(assigned_customers)

    products_by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for product in products:
        products_by_category[product["category"]].append(product)

    event_values = [
        "page_view",
        "product_view",
        "search",
        "cart_add",
        "checkout",
        "login",
        "email_click",
        "support_case",
    ]
    event_weights = [0.30, 0.22, 0.12, 0.12, 0.08, 0.08, 0.05, 0.03]
    event_counts: dict[str, int] = defaultdict(int)
    rows: list[dict[str, Any]] = []

    for event_index, customer_id in enumerate(assigned_customers, start=1):
        customer = customer_lookup[customer_id]
        profile = behavior[customer_id]
        start, end = activity_window(profile["cohort"], customer["signup_date"])
        event_ts = random_datetime(rng, start, end)
        event_type = str(rng.choice(event_values, p=event_weights))
        if event_type == "email_click" and not customer["marketing_opt_in"]:
            event_type = "page_view"

        if event_type == "email_click":
            channel = "email"
        elif event_type == "support_case":
            channel = "support"
        elif rng.random() < 0.75:
            channel = profile["preferred_channel"]
        else:
            channel = str(rng.choice(["web", "app", "store"]))

        product_id = None
        if event_type in {"product_view", "cart_add", "checkout"} or (
            event_type == "page_view" and rng.random() < 0.40
        ):
            product_pool = products_by_category[profile["preferred_category"]]
            product_id = product_pool[int(rng.integers(0, len(product_pool)))]["product_id"]

        event_counts[customer_id] += 1
        session_number = (event_counts[customer_id] - 1) // 4 + 1
        rows.append(
            {
                "event_id": f"EVT-{event_index:06d}",
                "customer_id": customer_id,
                "event_ts": event_ts,
                "event_type": event_type,
                "channel": channel,
                "session_id": f"SES-{customer_id[5:]}-{session_number:04d}",
                "product_id": product_id,
                "campaign_id": (
                    f"CMP-{int(rng.integers(1, 6)):03d}" if event_type == "email_click" else None
                ),
                "event_properties": {
                    "cohort": profile["cohort"],
                    "device": str(rng.choice(["mobile", "desktop", "tablet"], p=[0.58, 0.35, 0.07])),
                    "synthetic": "true",
                },
                "source_system": SOURCE_SYSTEM,
            }
        )

    return rows


def build_features_and_predictions(
    rng: np.random.Generator,
    customers: list[dict[str, Any]],
    behavior: dict[str, dict[str, str]],
    products: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
    transaction_items: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    product_lookup = {row["product_id"]: row for row in products}
    completed_transactions = {
        row["transaction_id"]: row
        for row in transactions
        if row["transaction_status"] == "completed"
    }
    transactions_by_customer: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for transaction in completed_transactions.values():
        transactions_by_customer[transaction["customer_id"]].append(transaction)

    events_by_customer: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        events_by_customer[event["customer_id"]].append(event)

    category_spend: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: money(0)))
    for item in transaction_items:
        transaction = completed_transactions.get(item["transaction_id"])
        if transaction is None:
            continue
        category = product_lookup[item["product_id"]]["category"]
        category_spend[transaction["customer_id"]][category] += item["line_amount"]

    feature_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []
    cohort_adjustment = {"loyal": -0.10, "active": -0.05, "new": 0.0, "at_risk": 0.15, "dormant": 0.25}
    propensity_adjustment = {"loyal": 0.10, "active": 0.05, "new": 0.03, "at_risk": -0.05, "dormant": -0.12}

    for customer in customers:
        customer_id = customer["customer_id"]
        customer_transactions = transactions_by_customer[customer_id]
        customer_events = events_by_customer[customer_id]
        last_purchase = max(row["transaction_ts"] for row in customer_transactions)
        days_since_last_purchase = max(0, (AS_OF_DATE - last_purchase.date()).days)
        tx_30d = [row for row in customer_transactions if row["transaction_ts"] >= AS_OF_TS - timedelta(days=30)]
        tx_90d = [row for row in customer_transactions if row["transaction_ts"] >= AS_OF_TS - timedelta(days=90)]
        events_30d = [row for row in customer_events if row["event_ts"] >= AS_OF_TS - timedelta(days=30)]
        lifetime_value = money(sum((row["total_amount"] for row in customer_transactions), money(0)))
        average_order_value = money(lifetime_value / len(customer_transactions))
        favorite_category = max(category_spend[customer_id], key=category_spend[customer_id].get)
        recency_score = round(max(0.0, 1.0 - days_since_last_purchase / 365.0), 6)

        feature_rows.append(
            {
                "customer_id": customer_id,
                "snapshot_date": AS_OF_DATE,
                "days_since_last_purchase": days_since_last_purchase,
                "purchases_30d": len(tx_30d),
                "purchases_90d": len(tx_90d),
                "spend_30d": money(sum((row["total_amount"] for row in tx_30d), money(0))),
                "spend_90d": money(sum((row["total_amount"] for row in tx_90d), money(0))),
                "lifetime_value": lifetime_value,
                "average_order_value": average_order_value,
                "engagement_events_30d": len(events_30d),
                "recency_score": recency_score,
                "favorite_category": favorite_category,
                "feature_version": "sample_v1",
                "computed_at": GENERATED_AT,
            }
        )

        cohort = behavior[customer_id]["cohort"]
        engagement_score = min(len(events_30d) / 20.0, 1.0)
        recent_cart = any(event["event_type"] == "cart_add" for event in events_30d)
        churn_probability = bounded(
            0.10
            + 0.65 * min(days_since_last_purchase / 365.0, 1.0)
            - 0.20 * engagement_score
            + cohort_adjustment[cohort]
            + float(rng.normal(0, 0.03))
        )
        purchase_propensity = bounded(
            0.10
            + 0.50 * recency_score
            + 0.25 * engagement_score
            + (0.10 if recent_cart else 0.0)
            + propensity_adjustment[cohort]
            + float(rng.normal(0, 0.03))
        )
        prediction_rows.append(
            {
                "prediction_id": f"PRED-{customer_id}-20260916",
                "customer_id": customer_id,
                "scored_at": GENERATED_AT,
                "model_name": "sample_churn_propensity",
                "model_version": "1.0",
                "churn_probability": churn_probability,
                "purchase_propensity_score": purchase_propensity,
                "predicted_next_category": favorite_category,
                "prediction_horizon_days": 30,
                "model_run_id": "synthetic-run-seed-42",
            }
        )

    return feature_rows, prediction_rows


def validate_locally(tables: dict[str, list[dict[str, Any]]]) -> None:
    expected_counts = {
        "customers": CUSTOMER_COUNT,
        "products": PRODUCT_COUNT,
        "transactions": TRANSACTION_COUNT,
        "transaction_items": TRANSACTION_ITEM_COUNT,
        "customer_events": EVENT_COUNT,
        "customer_features": CUSTOMER_COUNT,
        "customer_predictions": CUSTOMER_COUNT,
    }
    for name, rows in tables.items():
        frame = pl.DataFrame(rows, strict=False)
        assert frame.height == expected_counts[name], (name, frame.height)

    customers = tables["customers"]
    products = tables["products"]
    transactions = tables["transactions"]
    items = tables["transaction_items"]
    events = tables["customer_events"]
    features = tables["customer_features"]
    predictions = tables["customer_predictions"]

    customer_ids = {row["customer_id"] for row in customers}
    product_ids = {row["product_id"] for row in products}
    transaction_ids = {row["transaction_id"] for row in transactions}
    assert len(customer_ids) == CUSTOMER_COUNT
    assert len(product_ids) == PRODUCT_COUNT
    assert len(transaction_ids) == TRANSACTION_COUNT
    assert len({row["event_id"] for row in events}) == EVENT_COUNT
    assert len({(row["transaction_id"], row["line_number"]) for row in items}) == TRANSACTION_ITEM_COUNT
    assert {row["customer_id"] for row in transactions} == customer_ids
    assert {row["customer_id"] for row in events} == customer_ids
    assert {row["customer_id"] for row in features} == customer_ids
    assert {row["customer_id"] for row in predictions} == customer_ids
    assert all(row["transaction_id"] in transaction_ids for row in items)
    assert all(row["product_id"] in product_ids for row in items)
    assert all(row["product_id"] is None or row["product_id"] in product_ids for row in events)

    customer_signup = {row["customer_id"]: row["signup_date"] for row in customers}
    assert all(row["transaction_ts"].date() >= customer_signup[row["customer_id"]] for row in transactions)
    assert all(row["event_ts"].date() >= customer_signup[row["customer_id"]] for row in events)

    items_by_transaction: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        items_by_transaction[item["transaction_id"]].append(item)
    for transaction in transactions:
        transaction_lines = items_by_transaction[transaction["transaction_id"]]
        subtotal = money(sum((line["unit_price"] * line["quantity"] for line in transaction_lines), money(0)))
        discount = money(sum((line["discount_amount"] for line in transaction_lines), money(0)))
        tax = money((subtotal - discount) * Decimal("0.08"))
        assert transaction["subtotal_amount"] == subtotal
        assert transaction["discount_amount"] == discount
        assert transaction["tax_amount"] == tax
        assert transaction["total_amount"] == money(subtotal - discount + tax)


def spark_schemas() -> dict[str, Any]:
    from pyspark.sql.types import (
        BooleanType,
        DateType,
        DecimalType,
        DoubleType,
        IntegerType,
        MapType,
        StringType,
        StructField,
        StructType,
        TimestampType,
    )

    return {
        "customers": StructType([
            StructField("customer_id", StringType(), False),
            StructField("first_name", StringType()),
            StructField("last_name", StringType()),
            StructField("email", StringType()),
            StructField("phone", StringType()),
            StructField("date_of_birth", DateType()),
            StructField("signup_date", DateType(), False),
            StructField("segment", StringType()),
            StructField("loyalty_tier", StringType()),
            StructField("city", StringType()),
            StructField("state_province", StringType()),
            StructField("postal_code", StringType()),
            StructField("country_code", StringType()),
            StructField("preferred_channel", StringType()),
            StructField("marketing_opt_in", BooleanType(), False),
            StructField("account_status", StringType(), False),
            StructField("synthetic_record", BooleanType(), False),
            StructField("source_system", StringType(), False),
            StructField("source_updated_at", TimestampType()),
        ]),
        "products": StructType([
            StructField("product_id", StringType(), False),
            StructField("product_name", StringType(), False),
            StructField("category", StringType(), False),
            StructField("subcategory", StringType()),
            StructField("brand", StringType()),
            StructField("unit_cost", DecimalType(18, 2)),
            StructField("list_price", DecimalType(18, 2), False),
            StructField("active_flag", BooleanType(), False),
            StructField("source_system", StringType(), False),
        ]),
        "transactions": StructType([
            StructField("transaction_id", StringType(), False),
            StructField("customer_id", StringType(), False),
            StructField("transaction_ts", TimestampType(), False),
            StructField("channel", StringType(), False),
            StructField("store_id", StringType()),
            StructField("currency_code", StringType(), False),
            StructField("subtotal_amount", DecimalType(18, 2), False),
            StructField("discount_amount", DecimalType(18, 2), False),
            StructField("tax_amount", DecimalType(18, 2), False),
            StructField("total_amount", DecimalType(18, 2), False),
            StructField("payment_method", StringType()),
            StructField("transaction_status", StringType(), False),
            StructField("source_system", StringType(), False),
        ]),
        "transaction_items": StructType([
            StructField("transaction_id", StringType(), False),
            StructField("line_number", IntegerType(), False),
            StructField("product_id", StringType(), False),
            StructField("quantity", IntegerType(), False),
            StructField("unit_price", DecimalType(18, 2), False),
            StructField("discount_amount", DecimalType(18, 2), False),
            StructField("line_amount", DecimalType(18, 2), False),
        ]),
        "customer_events": StructType([
            StructField("event_id", StringType(), False),
            StructField("customer_id", StringType(), False),
            StructField("event_ts", TimestampType(), False),
            StructField("event_type", StringType(), False),
            StructField("channel", StringType(), False),
            StructField("session_id", StringType()),
            StructField("product_id", StringType()),
            StructField("campaign_id", StringType()),
            StructField("event_properties", MapType(StringType(), StringType())),
            StructField("source_system", StringType(), False),
        ]),
        "customer_features": StructType([
            StructField("customer_id", StringType(), False),
            StructField("snapshot_date", DateType(), False),
            StructField("days_since_last_purchase", IntegerType()),
            StructField("purchases_30d", IntegerType(), False),
            StructField("purchases_90d", IntegerType(), False),
            StructField("spend_30d", DecimalType(18, 2), False),
            StructField("spend_90d", DecimalType(18, 2), False),
            StructField("lifetime_value", DecimalType(18, 2), False),
            StructField("average_order_value", DecimalType(18, 2)),
            StructField("engagement_events_30d", IntegerType(), False),
            StructField("recency_score", DoubleType()),
            StructField("favorite_category", StringType()),
            StructField("feature_version", StringType(), False),
            StructField("computed_at", TimestampType(), False),
        ]),
        "customer_predictions": StructType([
            StructField("prediction_id", StringType(), False),
            StructField("customer_id", StringType(), False),
            StructField("scored_at", TimestampType(), False),
            StructField("model_name", StringType(), False),
            StructField("model_version", StringType(), False),
            StructField("churn_probability", DoubleType()),
            StructField("purchase_propensity_score", DoubleType()),
            StructField("predicted_next_category", StringType()),
            StructField("prediction_horizon_days", IntegerType()),
            StructField("model_run_id", StringType()),
        ]),
    }


def merge_rows(
    spark: Any,
    catalog: str,
    schema: str,
    table: str,
    rows: list[dict[str, Any]],
    spark_schema: Any,
    keys: list[str],
) -> None:
    source_view = f"sample_{table}_source"
    source_df = spark.createDataFrame(rows, schema=spark_schema)
    source_df.createOrReplaceTempView(source_view)
    columns = [field.name for field in spark_schema.fields]
    on_clause = " AND ".join(f"target.{column} = source.{column}" for column in keys)
    update_columns = [column for column in columns if column not in keys]
    update_clause = ",\n      ".join(
        f"target.{column} = source.{column}" for column in update_columns
    )
    insert_columns = ", ".join(columns)
    insert_values = ", ".join(f"source.{column}" for column in columns)
    target = table_name(catalog, schema, table)
    spark.sql(
        f"""
        MERGE INTO {target} AS target
        USING {source_view} AS source
        ON {on_clause}
        WHEN MATCHED THEN UPDATE SET
          {update_clause}
        WHEN NOT MATCHED THEN INSERT ({insert_columns})
        VALUES ({insert_values})
        """
    ).collect()


def write_to_unity_catalog(
    tables: dict[str, list[dict[str, Any]]], catalog: str, schema: str, profile: str
) -> None:
    os.environ["DATABRICKS_CONFIG_PROFILE"] = profile
    from databricks.connect import DatabricksSession

    spark = DatabricksSession.builder.serverless().getOrCreate()
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    spark.sql(
        f"CREATE SCHEMA IF NOT EXISTS {quote_identifier(catalog)}.{quote_identifier(schema)}"
    ).collect()

    schemas = spark_schemas()
    merge_keys = {
        "customers": ["customer_id"],
        "products": ["product_id"],
        "transactions": ["transaction_id"],
        "transaction_items": ["transaction_id", "line_number"],
        "customer_events": ["event_id"],
        "customer_features": ["customer_id", "snapshot_date"],
        "customer_predictions": ["prediction_id"],
    }
    for name in [
        "customers",
        "products",
        "transactions",
        "transaction_items",
        "customer_events",
        "customer_features",
        "customer_predictions",
    ]:
        merge_rows(spark, catalog, schema, name, tables[name], schemas[name], merge_keys[name])
        print(f"Merged {len(tables[name]):,} rows into {catalog}.{schema}.{name}")

    expected_counts = {
        "customers": 50,
        "products": 40,
        "transactions": 1_000,
        "transaction_items": 2_500,
        "customer_events": 2_000,
        "customer_features": 50,
        "customer_predictions": 50,
    }
    for name, expected in expected_counts.items():
        actual = spark.sql(f"SELECT count(*) AS count FROM {table_name(catalog, schema, name)}").first()["count"]
        if actual != expected:
            raise RuntimeError(f"Expected {expected} rows in {name}, found {actual}")

    customer_360_count = spark.sql(
        f"SELECT count(*) AS count FROM {table_name(catalog, schema, 'customer_360')}"
    ).first()["count"]
    if customer_360_count != CUSTOMER_COUNT:
        raise RuntimeError(
            f"Expected {CUSTOMER_COUNT} rows in customer_360, found {customer_360_count}"
        )
    spark.stop()


def generate() -> dict[str, list[dict[str, Any]]]:
    rng = np.random.default_rng(SEED)
    generic = Generic(locale=Locale.EN, seed=SEED)
    customers, behavior = build_customers(rng, generic)
    products = build_products(rng)
    transactions, transaction_items = build_transactions_and_items(
        rng, customers, behavior, products
    )
    customer_events = build_events(rng, customers, behavior, products)
    customer_features, customer_predictions = build_features_and_predictions(
        rng,
        customers,
        behavior,
        products,
        transactions,
        transaction_items,
        customer_events,
    )
    tables = {
        "customers": customers,
        "products": products,
        "transactions": transactions,
        "transaction_items": transaction_items,
        "customer_events": customer_events,
        "customer_features": customer_features,
        "customer_predictions": customer_predictions,
    }
    validate_locally(tables)
    return tables


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="databricks-hackathon")
    parser.add_argument("--schema", default="00data")
    parser.add_argument("--profile", default="bloomreach-hackathon-workspace")
    parser.add_argument(
        "--dry-run", action="store_true", help="Generate and validate locally without writing"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tables = generate()
    print("Local validation passed:")
    for name, rows in tables.items():
        preview = pl.DataFrame(rows, strict=False).head(3)
        print(f"\n{name}: {len(rows):,} rows")
        print(preview)
    if not args.dry_run:
        write_to_unity_catalog(tables, args.catalog, args.schema, args.profile)
        print("\nUnity Catalog population and row-count validation passed.")


if __name__ == "__main__":
    main()
