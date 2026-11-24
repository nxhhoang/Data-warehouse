"""Generate a small GA4-like JSONL fixture for local pipeline dry-runs.

Writes a deterministic set of synthetic events that exercise every branch of
the pipeline: valid events, a purchase without transaction_id, a purchase with
zero revenue, an exact duplicate, an event without ga_session_id, placeholder
values, a malformed JSON line and an event with a missing event_date.

Usage:
    python scripts/make_test_fixture.py [--output tests/fixtures/ga4_events_sample.jsonl] [--force]

Expected routing for the default fixture (verify in build/pipeline_dry_run):
    valid events    : 4   (events 1, 2, 3, 7)
    dropped purchases: 2   (missing transaction_id, zero revenue)
    deduped         : 1   (duplicate of event 3)
    dead letter     : 2   (malformed JSON, missing event_date)
    quality log     : 4 rows (2 purchase drops, 1 duplicate_event, 1 missing_session_id)

Note: integers are rendered as strings on purpose — BigQuery TO_JSON_STRING
encodes INT64 that way, and the fixture mimics real publisher output.
"""

import argparse
import json
from pathlib import Path

DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "ga4_events_sample.jsonl"


def base_event(event_name: str, timestamp: str, session_id: int, bundle_id: str,
               user: str = "1234567890.1234567890") -> dict:
    """Build a minimal GA4-shaped event with the fields the models read."""
    return {
        "event_date": "20201101",
        "event_timestamp": timestamp,
        "event_name": event_name,
        "event_bundle_sequence_id": bundle_id,
        "user_pseudo_id": user,
        "user_first_touch_timestamp": "1604188800000000",
        "event_params": [
            {"key": "ga_session_id", "value": {"int_value": str(session_id)}},
            {"key": "ga_session_number", "value": {"int_value": "1"}},
            {"key": "engagement_time_msec", "value": {"int_value": "1500"}},
            {"key": "page_location", "value": {"string_value": "https://shop.googlemerchandisestore.com/"}},
            {"key": "page_title", "value": {"string_value": "Google Merchandise Store"}},
        ],
        "traffic_source": {"source": "google", "medium": "organic", "name": "(not set)"},
        "device": {
            "category": "desktop",
            "operating_system": "Windows",
            "web_info": {"browser": "Chrome"},
            "language": "en-us",
        },
        "geo": {"continent": "Americas", "country": "United States", "region": None, "city": None},
        "ecommerce": {},
        "items": [],
    }


def build_events() -> list:
    events = []

    # 1. Valid page_view with session-level source params
    page_view = base_event("page_view", "1604233848000123", 1001, "1001")
    page_view["event_params"].extend([
        {"key": "source", "value": {"string_value": "google"}},
        {"key": "medium", "value": {"string_value": "organic"}},
    ])
    events.append(page_view)

    # 2. Valid view_item with an item row
    view_item = base_event("view_item", "1604233855000456", 1001, "1002")
    view_item["items"].append({
        "item_id": "GGOEGXXX0101", "item_name": "Google Bike Enamel Pin",
        "item_brand": "Google", "item_variant": "Red",
        "item_category": "Apparel", "item_category2": "Accessories",
        "item_category3": None, "price": None, "price_in_usd": None,
        "quantity": None, "item_revenue": None, "item_revenue_in_usd": None,
    })
    events.append(view_item)

    # 3. Valid purchase with transaction_id, revenue and items
    purchase = base_event("purchase", "1604233900000789", 1001, "1003")
    purchase["ecommerce"] = {
        "transaction_id": "AT-001", "purchase_revenue_in_usd": 129.0,
        "total_item_quantity": "2",
    }
    purchase["items"].append({
        "item_id": "GGOEGXXX0101", "item_name": "Google Bike Enamel Pin",
        "item_brand": "Google", "item_variant": "Red",
        "item_category": "Apparel", "item_category2": "Accessories",
        "item_category3": None, "price": "5.5", "price_in_usd": "5.5",
        "quantity": "2", "item_revenue": "11.0", "item_revenue_in_usd": "11.0",
    })
    events.append(purchase)

    # 4. Purchase without transaction_id -> dropped (purchase_without_transaction_id)
    bad_purchase = base_event("purchase", "1604233950000001", 1001, "1004")
    bad_purchase["ecommerce"] = {"transaction_id": "(not set)", "purchase_revenue_in_usd": 59.0}
    events.append(bad_purchase)

    # 5. Purchase with zero revenue -> dropped (negative_or_zero_revenue)
    zero_purchase = base_event("purchase", "1604233960000002", 1001, "1005")
    zero_purchase["ecommerce"] = {"transaction_id": "AT-002", "purchase_revenue_in_usd": 0.0}
    events.append(zero_purchase)

    # 6. Exact duplicate of event 3 (same identity fields) -> deduped within window
    events.append(json.loads(json.dumps(purchase)))

    # 7. Event without ga_session_id -> kept, logged (missing_session_id);
    #    placeholder sources are nulled by normalization
    no_session = base_event("user_engagement", "1604233970000003", 0, "1006", user="9876543210.9876543210")
    no_session["event_params"] = [p for p in no_session["event_params"] if p["key"] != "ga_session_id"]
    no_session["traffic_source"] = {"source": "<Other>", "medium": "<Other>", "name": "(data deleted)"}
    events.append(no_session)

    return events


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="output JSONL path")
    parser.add_argument("--force", action="store_true", help="overwrite an existing fixture")
    args = parser.parse_args()

    out_path = Path(args.output)
    if out_path.exists() and not args.force:
        print(f"Fixture already exists: {out_path} (use --force to overwrite)")
        return 0
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [json.dumps(e, ensure_ascii=False) for e in build_events()]
    lines.append("{not valid json,,")  # 8. Malformed JSON -> dead letter
    broken = base_event("page_view", "1604233980000004", 1001, "1007")
    del broken["event_date"]           # 9. Missing event_date -> dead letter
    lines.append(json.dumps(broken, ensure_ascii=False))

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Fixture written: {out_path} ({len(lines)} lines)")
    print("Run the dry-run with:")
    print("  python src/pipeline/dataflow_pipeline.py "
          f"--input_file {out_path} --output_dir build/pipeline_dry_run --runner=DirectRunner")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
