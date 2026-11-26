"""Transform layer — Dataflow / Apache Beam pipeline (report section 3.3, layer 3).

Consumes JSON messages from Pub/Sub, validates and normalizes them, detects
duplicates and quality-rule violations, then writes valid events into the raw
tables events_YYYYMMDD (sharded by event date) in a BigQuery raw dataset.

Division of labor with the dbt staging layer (report section 3.3):
- The pipeline keeps each record's nested structure (event_params, items,
  ecommerce, device, geo, traffic_source) so the raw schema is compatible with
  both the public dataset and the pipeline output.
- Flattening event_params, exploding items into per-item rows and combining
  user_pseudo_id + ga_session_id into a session id happen in dbt staging.

Quality rules are read from config/quality_rules.yaml (single source of truth
shared by layer 3 and layer 4): placeholder values, the event key fields used
for deduplication, and invalid-record handling.

Local run (DirectRunner, requires real topic/subscription):
  python src/pipeline/dataflow_pipeline.py \\
      --project=your-project --region=asia-southeast1 \\
      --input_subscription=projects/your-project/subscriptions/ga4-events-sub \\
      --raw_dataset=marketing_dss_raw --runner=DirectRunner

Dataflow run: switch to --runner=DataflowRunner and add --temp_location,
--staging_location and --service_account_email for your project.

BigQuery Sandbox note (survey section 4): the Sandbox does not support
streaming inserts, so writes default to FILE_LOADS (slower batch load jobs
but works inside the Sandbox). With billing enabled you can switch
--write_method to STREAMING_INSERTS.

Local dry-run (no GCP account needed at all):
  python scripts/make_test_fixture.py
  python src/pipeline/dataflow_pipeline.py \\
      --input_file tests/fixtures/ga4_events_sample.jsonl \\
      --output_dir build/pipeline_dry_run --runner=DirectRunner
In file mode the pipeline reads JSON lines instead of Pub/Sub, stamps each
event with its own event_timestamp, and writes valid events, dead-letter
rows and quality-log rows as JSONL files instead of BigQuery tables.
"""

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import apache_beam as beam
from apache_beam.options.pipeline_options import PipelineOptions, StandardOptions
from apache_beam.pvalue import TaggedOutput

LOGGER = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "quality_rules.yaml"

# Schema of the raw events_YYYYMMDD tables: the subset of the GA4 export
# schema that the staging layer reads (stg_ga4_events, stg_ga4_items),
# keeping the original nested shape.
RAW_EVENTS_SCHEMA = {
    "fields": [
        {"name": "event_date", "type": "STRING", "mode": "REQUIRED"},
        {"name": "event_timestamp", "type": "INTEGER", "mode": "REQUIRED"},
        {"name": "event_name", "type": "STRING", "mode": "REQUIRED"},
        {"name": "event_bundle_sequence_id", "type": "INTEGER"},
        {"name": "user_pseudo_id", "type": "STRING"},
        {"name": "user_first_touch_timestamp", "type": "INTEGER"},
        {
            "name": "event_params",
            "type": "RECORD",
            "mode": "REPEATED",
            "fields": [
                {"name": "key", "type": "STRING"},
                {
                    "name": "value",
                    "type": "RECORD",
                    "fields": [
                        {"name": "string_value", "type": "STRING"},
                        {"name": "int_value", "type": "INTEGER"},
                        {"name": "float_value", "type": "FLOAT"},
                        {"name": "double_value", "type": "FLOAT"},
                    ],
                },
            ],
        },
        {
            "name": "traffic_source",
            "type": "RECORD",
            "fields": [
                {"name": "source", "type": "STRING"},
                {"name": "medium", "type": "STRING"},
                {"name": "name", "type": "STRING"},
            ],
        },
        {
            "name": "device",
            "type": "RECORD",
            "fields": [
                {"name": "category", "type": "STRING"},
                {"name": "operating_system", "type": "STRING"},
                {
                    "name": "web_info",
                    "type": "RECORD",
                    "fields": [{"name": "browser", "type": "STRING"}],
                },
                {"name": "language", "type": "STRING"},
            ],
        },
        {
            "name": "geo",
            "type": "RECORD",
            "fields": [
                {"name": "continent", "type": "STRING"},
                {"name": "country", "type": "STRING"},
                {"name": "region", "type": "STRING"},
                {"name": "city", "type": "STRING"},
            ],
        },
        {
            "name": "ecommerce",
            "type": "RECORD",
            "fields": [
                {"name": "transaction_id", "type": "STRING"},
                {"name": "purchase_revenue_in_usd", "type": "FLOAT"},
                {"name": "total_item_quantity", "type": "INTEGER"},
            ],
        },
        {
            "name": "items",
            "type": "RECORD",
            "mode": "REPEATED",
            "fields": [
                {"name": "item_id", "type": "STRING"},
                {"name": "item_name", "type": "STRING"},
                {"name": "item_brand", "type": "STRING"},
                {"name": "item_variant", "type": "STRING"},
                {"name": "item_category", "type": "STRING"},
                {"name": "item_category2", "type": "STRING"},
                {"name": "item_category3", "type": "STRING"},
                {"name": "price", "type": "FLOAT"},
                {"name": "price_in_usd", "type": "FLOAT"},
                {"name": "quantity", "type": "INTEGER"},
                {"name": "item_revenue", "type": "FLOAT"},
                {"name": "item_revenue_in_usd", "type": "FLOAT"},
            ],
        },
    ]
}

# Columns match config/quality_rules.yaml -> quality_log.fields
QUALITY_LOG_SCHEMA = {
    "fields": [
        {"name": "run_date", "type": "DATE", "mode": "REQUIRED"},
        {"name": "rule_name", "type": "STRING", "mode": "REQUIRED"},
        {"name": "table", "type": "STRING", "mode": "REQUIRED"},
        {"name": "affected_rows", "type": "INTEGER", "mode": "REQUIRED"},
        {"name": "action", "type": "STRING", "mode": "REQUIRED"},
        {"name": "detail", "type": "STRING"},
    ]
}

DEAD_LETTER_SCHEMA = {
    "fields": [
        {"name": "payload", "type": "STRING", "mode": "REQUIRED"},
        {"name": "error", "type": "STRING", "mode": "REQUIRED"},
        {"name": "received_at", "type": "TIMESTAMP", "mode": "REQUIRED"},
    ]
}


def load_quality_config(path: str) -> dict:
    """Read config/quality_rules.yaml on the job-submission machine.

    Values are passed into DoFns as constructor arguments, so workers do not
    need to read the file themselves.

    Parameters
    ----------
    path : str
        Path to config/quality_rules.yaml.

    Returns
    -------
    dict
        Keys 'placeholder_values' (list of str) and 'event_key_fields'
        (list of str), falling back to documented defaults if the file
        is missing.
    """
    config_path = Path(path)
    if not config_path.exists():
        LOGGER.warning("Config not found at %s, using defaults", path)
        return {
            "placeholder_values": ["<Other>", "(data deleted)", "(not set)", ""],
            "event_key_fields": [
                "user_pseudo_id", "event_timestamp", "event_name",
                "event_bundle_sequence_id",
            ],
        }
    # Lazy import: keeps pyyaml off the Dataflow workers, which only import
    # this module for its DoFn classes — this function runs once, on the
    # job-submission machine only.
    import yaml
    with config_path.open(encoding="utf-8") as handle:
        rules = yaml.safe_load(handle) or {}
    return {
        "placeholder_values": rules.get("placeholder_values",
                                        ["<Other>", "(data deleted)", "(not set)", ""]),
        "event_key_fields": rules.get("duplicate_check", {}).get(
            "event_key_fields",
            ["user_pseudo_id", "event_timestamp", "event_name",
             "event_bundle_sequence_id"],
        ),
    }


def _to_int(value):
    """Coerce to int; BigQuery TO_JSON_STRING renders INT64 as a string."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _has_session_id(event) -> bool:
    """Return True if the event carries a usable ga_session_id param."""
    for param in event.get("event_params") or []:
        if param.get("key") == "ga_session_id":
            value = param.get("value") or {}
            return value.get("int_value") is not None
    return False


def _null_placeholders(value, placeholders):
    """Recursively replace placeholder strings with None, keeping structure."""
    if isinstance(value, str) and value in placeholders:
        return None
    if isinstance(value, dict):
        return {k: _null_placeholders(v, placeholders) for k, v in value.items()}
    if isinstance(value, list):
        return [_null_placeholders(v, placeholders) for v in value]
    return value


class ParseJsonDoFn(beam.DoFn):
    """Decode a JSON message; failures go to the dead-letter output with a reason.

    Accepts both bytes (Pub/Sub) and str (ReadFromText in dry-run mode).
    """

    DEAD_TAG = "dead_letter"

    def process(self, element):
        received_at = datetime.now(timezone.utc).isoformat()
        raw = element.decode("utf-8", errors="replace") if isinstance(element, bytes) else element
        try:
            event = json.loads(raw)
            if not isinstance(event, dict):
                raise ValueError("message is not a JSON object")
            yield event
        except (ValueError, TypeError) as err:
            yield TaggedOutput(
                self.DEAD_TAG,
                {
                    "payload": raw,
                    "error": f"json_parse: {err}",
                    "received_at": received_at,
                },
            )


class NormalizeEventDoFn(beam.DoFn):
    """Validate required fields, coerce types, null placeholders and fill
    empty structures so every record has the same shape."""

    DEAD_TAG = "dead_letter"

    def __init__(self, placeholders):
        self.placeholders = tuple(placeholders)

    def process(self, event):
        received_at = datetime.now(timezone.utc).isoformat()
        event_date = event.get("event_date")
        if (not isinstance(event_date, str) or len(event_date) != 8
                or not event_date.isdigit()):
            yield TaggedOutput(self.DEAD_TAG, {
                "payload": json.dumps(event, ensure_ascii=False),
                "error": "missing_or_invalid: event_date",
                "received_at": received_at,
            })
            return
        if not event.get("event_name") or event.get("event_timestamp") is None:
            yield TaggedOutput(self.DEAD_TAG, {
                "payload": json.dumps(event, ensure_ascii=False),
                "error": "missing_or_invalid: event_name/event_timestamp",
                "received_at": received_at,
            })
            return

        event["event_timestamp"] = _to_int(event["event_timestamp"])
        event["event_bundle_sequence_id"] = _to_int(event.get("event_bundle_sequence_id"))
        event["user_first_touch_timestamp"] = _to_int(event.get("user_first_touch_timestamp"))
        event.setdefault("user_pseudo_id", None)
        event.setdefault("event_params", [])
        event.setdefault("items", [])
        event.setdefault("traffic_source", {})
        event.setdefault("device", {}).setdefault("web_info", {})
        event.setdefault("geo", {})
        event.setdefault("ecommerce", {})

        for param in event["event_params"]:
            value = param.setdefault("value", {})
            value["int_value"] = _to_int(value.get("int_value"))
        for item in event["items"]:
            item["quantity"] = _to_int(item.get("quantity"))
        ecommerce = event["ecommerce"]
        ecommerce["total_item_quantity"] = _to_int(ecommerce.get("total_item_quantity"))

        event = _null_placeholders(event, self.placeholders)
        yield event


class ClassifyQualityDoFn(beam.DoFn):
    """Apply the invalid_records rules of config/quality_rules.yaml.

    purchase_without_transaction_id and negative_or_zero_revenue:
    drop_and_log. missing_session_id: use_unknown_dimension (kept, only
    logged for information).
    """

    QUALITY_TAG = "quality"

    def __init__(self, purchase_rules):
        self.purchase_rules = purchase_rules

    @staticmethod
    def _log_record(rule, action, detail):
        return {
            "run_date": datetime.now(timezone.utc).date().isoformat(),
            "rule_name": rule,
            "table": "events",
            "affected_rows": 1,
            "action": action,
            "detail": detail,
        }

    def process(self, event):
        if not _has_session_id(event):
            yield TaggedOutput(self.QUALITY_TAG, self._log_record(
                "missing_session_id", "use_unknown_dimension",
                f"event_name={event.get('event_name')}",
            ))
        if event.get("event_name") != "purchase":
            yield event
            return
        ecommerce = event.get("ecommerce") or {}
        transaction_id = ecommerce.get("transaction_id")
        revenue = ecommerce.get("purchase_revenue_in_usd")
        if self.purchase_rules and not transaction_id:
            yield TaggedOutput(self.QUALITY_TAG, self._log_record(
                "purchase_without_transaction_id", "drop_and_log",
                f"user_pseudo_id={event.get('user_pseudo_id')}",
            ))
            return
        if self.purchase_rules and (revenue is None or revenue <= 0):
            yield TaggedOutput(self.QUALITY_TAG, self._log_record(
                "negative_or_zero_revenue", "drop_and_log",
                f"transaction_id={transaction_id}",
            ))
            return
        yield event


class DedupeEventsDoFn(beam.DoFn):
    """Deduplicate within a time window using the configured event key.

    Receives (event_key, [events]) after GroupByKey: emits the first event
    and logs the number of duplicates to the quality log. Global
    deduplication is still guaranteed downstream in the staging layer
    (QUALIFY in stg_ga4_events).
    """

    QUALITY_TAG = "quality"

    def process(self, keyed_events):
        _, events = keyed_events
        events = list(events)
        yield events[0]
        if len(events) > 1:
            yield TaggedOutput(self.QUALITY_TAG, {
                "run_date": datetime.now(timezone.utc).date().isoformat(),
                "rule_name": "duplicate_event",
                "table": "events",
                "affected_rows": len(events) - 1,
                "action": "drop_and_log",
                "detail": "duplicates sharing (user_pseudo_id, event_timestamp, "
                          "event_name, event_bundle_sequence_id) within a window",
            })


def split_batch_payload(payload):
    """Yield unchanged raw event strings from a replay batch wire payload."""
    raw = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
    decoded = json.loads(raw)
    if isinstance(decoded, str):
        # A batch-size-n replay can end with a single remaining event.
        yield decoded
        return
    if not isinstance(decoded, list) or not all(isinstance(item, str) for item in decoded):
        raise ValueError("Batched replay input must be a JSON array of raw payload strings")
    yield from decoded


def build_pipeline(argv):
    """Construct the Beam pipeline from CLI arguments.

    Parameters
    ----------
    argv : list of str
        Argument list without the program name; unknown flags are forwarded
        to PipelineOptions (e.g. --runner, --project, --region).

    Raises
    ------
    SystemExit
        If neither --bq_project nor --project is provided.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--use_bundle_direct_runner", action="store_true",
                        help="use BundleBasedDirectRunner; skips the Prism trial that "
                             "does not implement Pub/Sub reads")
    parser.add_argument("--input_subscription", default=None,
                        help="projects/<project>/subscriptions/<sub> (streaming mode)")
    parser.add_argument("--input_file", default=None,
                        help="JSONL file of events (local dry-run mode, replaces Pub/Sub)")
    parser.add_argument("--json_batches", action="store_true",
                        help="decode Pub/Sub messages as JSON arrays containing raw event strings")
    parser.add_argument("--output_dir", default=None,
                        help="write JSONL outputs here instead of BigQuery (dry-run mode)")
    parser.add_argument("--raw_dataset", default="marketing_dss_raw",
                        help="BigQuery raw dataset (e.g. marketing_dss_raw); "
                             "ignored in dry-run mode")
    parser.add_argument("--bq_project", default=None,
                        help="project holding the raw dataset; defaults to --project")
    parser.add_argument("--dead_letter_table", default=None)
    parser.add_argument("--quality_log_table", default=None)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH),
                        help="path to config/quality_rules.yaml")
    parser.add_argument("--dedup_window_sec", type=int, default=600)
    parser.add_argument("--write_method", default="FILE_LOADS",
                        choices=["FILE_LOADS", "STREAMING_INSERTS"],
                        help="FILE_LOADS works inside the BigQuery Sandbox")
    parser.add_argument("--triggering_frequency", type=int, default=60,
                        help="seconds between load jobs when using FILE_LOADS")
    known_args, pipeline_args = parser.parse_known_args(argv)

    if not known_args.input_subscription and not known_args.input_file:
        raise SystemExit("Need --input_subscription or --input_file")

    config = load_quality_config(known_args.config)
    placeholders = config["placeholder_values"]
    key_fields = config["event_key_fields"]
    purchase_rules = True  # purchase_without_transaction_id + negative_or_zero_revenue

    bq_project = known_args.bq_project
    if bq_project is None:
        bq_project = next(
            (arg.split("=", 1)[1] for arg in pipeline_args
             if arg.startswith("--project=")),
            None,
        )

    # BigQuery side is only wired up when not in dry-run mode; the dry-run
    # writes local JSONL files and needs no project at all.
    dead_letter_table = None
    quality_log_table = None
    write_options = None
    raw_table_fn = None
    if known_args.output_dir is None:
        if bq_project is None:
            raise SystemExit("Need --bq_project or --project=<gcp-project-id>")
        dead_letter_table = known_args.dead_letter_table or \
            f"{bq_project}:{known_args.raw_dataset}.dead_letter"
        quality_log_table = known_args.quality_log_table or \
            f"{bq_project}:{known_args.raw_dataset}.quality_log"
        write_options = {
            "method": beam.io.WriteToBigQuery.Method(known_args.write_method),
        }
        if known_args.write_method == "FILE_LOADS":
            write_options["triggering_frequency"] = known_args.triggering_frequency

        def raw_table_fn(event):
            return f"{bq_project}:{known_args.raw_dataset}.events_{event['event_date']}"

    def event_key(event):
        return json.dumps([event.get(field) for field in key_fields])

    pipeline_options = PipelineOptions(pipeline_args)
    pipeline_options.view_as(StandardOptions).streaming = known_args.input_file is None

    runner = None
    if known_args.use_bundle_direct_runner:
        from apache_beam.runners.direct.direct_runner import BundleBasedDirectRunner
        runner = BundleBasedDirectRunner()

    with beam.Pipeline(runner=runner, options=pipeline_options) as pipeline:
        if known_args.input_file:
            messages = pipeline | "ReadFile" >> beam.io.ReadFromText(known_args.input_file)
        else:
            messages = pipeline | "ReadPubSub" >> beam.io.ReadFromPubSub(
                subscription=known_args.input_subscription
            )

        if known_args.json_batches:
            messages = messages | "UnpackReplayBatches" >> beam.FlatMap(split_batch_payload)

        parsed = messages | "ParseJson" >> beam.ParDo(ParseJsonDoFn()).with_outputs(
            ParseJsonDoFn.DEAD_TAG, main="valid"
        )

        normalized = parsed.valid | "NormalizeEvent" >> beam.ParDo(
            NormalizeEventDoFn(placeholders)
        ).with_outputs(NormalizeEventDoFn.DEAD_TAG, main="valid")

        valid_events = normalized.valid
        if known_args.input_file:
            # Stamp AFTER normalization so event_timestamp is already an int;
            # this gives the dedup windows real event-time meaning in dry-run
            # mode instead of the default processing-time timestamp.
            valid_events = valid_events | "StampEventTime" >> beam.Map(
                lambda e: beam.window.TimestampedValue(e, e["event_timestamp"] / 1e6)
            )

        # Window every branch once, right before the stages that branch into
        # side outputs, so the downstream Flattens always combine PCollections
        # with the same windowing strategy (side outputs inherit it).
        windowed_valid = valid_events | "WindowEvents" >> beam.WindowInto(
            beam.window.FixedWindows(known_args.dedup_window_sec))

        classified = windowed_valid | "ClassifyQuality" >> beam.ParDo(
            ClassifyQualityDoFn(purchase_rules)
        ).with_outputs(ClassifyQualityDoFn.QUALITY_TAG, main="valid")

        deduped = (
            classified.valid
            | "KeyByEventKey" >> beam.Map(lambda e: (event_key(e), e))
            | "GroupByKey" >> beam.GroupByKey()
            | "Dedupe" >> beam.ParDo(DedupeEventsDoFn()).with_outputs(
                DedupeEventsDoFn.QUALITY_TAG, main="valid")
        )

        dead_letter = (
            (parsed.dead_letter, normalized.dead_letter)
            | "FlattenDeadLetter" >> beam.Flatten()
            | "WindowDeadLetter" >> beam.WindowInto(
                beam.window.FixedWindows(known_args.dedup_window_sec))
        )
        quality = (
            (classified.quality, deduped.quality)
            | "FlattenQuality" >> beam.Flatten()
        )

        if known_args.output_dir:
            # Dry-run sinks: plain JSONL files, no BigQuery involved.
            out_dir = Path(known_args.output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            (
                deduped.valid
                | "FormatValidEvents" >> beam.Map(lambda e: json.dumps(e, ensure_ascii=False))
                | "WriteValidEvents" >> beam.io.WriteToText(
                    str(out_dir / "events"), file_name_suffix=".jsonl")
            )
            (
                dead_letter
                | "FormatDeadLetter" >> beam.Map(lambda r: json.dumps(r, ensure_ascii=False))
                | "WriteDeadLetterFile" >> beam.io.WriteToText(
                    str(out_dir / "dead_letter"), file_name_suffix=".jsonl")
            )
            (
                quality
                | "FormatQualityLog" >> beam.Map(lambda r: json.dumps(r, ensure_ascii=False))
                | "WriteQualityLogFile" >> beam.io.WriteToText(
                    str(out_dir / "quality_log"), file_name_suffix=".jsonl")
            )
        else:
            (
                deduped.valid
                | "WriteRawEvents" >> beam.io.WriteToBigQuery(
                    table=raw_table_fn,
                    schema=RAW_EVENTS_SCHEMA,
                    create_disposition=beam.io.BigQueryDisposition.CREATE_IF_NEEDED,
                    write_disposition=beam.io.BigQueryDisposition.WRITE_APPEND,
                    **write_options,
                )
            )
            (
                dead_letter
                | "WriteDeadLetter" >> beam.io.WriteToBigQuery(
                    table=dead_letter_table,
                    schema=DEAD_LETTER_SCHEMA,
                    create_disposition=beam.io.BigQueryDisposition.CREATE_IF_NEEDED,
                    write_disposition=beam.io.BigQueryDisposition.WRITE_APPEND,
                    **write_options,
                )
            )
            (
                quality
                | "WriteQualityLog" >> beam.io.WriteToBigQuery(
                    table=quality_log_table,
                    schema=QUALITY_LOG_SCHEMA,
                    create_disposition=beam.io.BigQueryDisposition.CREATE_IF_NEEDED,
                    write_disposition=beam.io.BigQueryDisposition.WRITE_APPEND,
                    **write_options,
                )
            )


def main():
    import sys
    logging.basicConfig(level=logging.INFO)
    build_pipeline(sys.argv[1:])


if __name__ == "__main__":
    main()
