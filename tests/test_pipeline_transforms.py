"""Unit tests for the Dataflow pipeline transforms (no GCP account needed).

Each DoFn is invoked directly through its process() method, so these tests
run in milliseconds without a Beam runner; TaggedOutput values are routed by
their tag exactly like ParDo would do inside a pipeline.
Run from the repository root:  pytest tests/test_pipeline_transforms.py
"""

import json

import pytest
from apache_beam.pvalue import TaggedOutput

from src.pipeline.dataflow_pipeline import (
    ClassifyQualityDoFn,
    DedupeEventsDoFn,
    NormalizeEventDoFn,
    ParseJsonDoFn,
    load_quality_config,
)

PLACEHOLDERS = ["<Other>", "(data deleted)", "(not set)", ""]


def run_dofn(dofn, element):
    """Invoke process() once; return (main_outputs, {tag: [side outputs]})."""
    main, side = [], {}
    for out in dofn.process(element):
        if isinstance(out, TaggedOutput):
            side.setdefault(out.tag, []).append(out.value)
        else:
            main.append(out)
    return main, side


def valid_event(event_name="page_view", timestamp="1604233848000123"):
    return {
        "event_date": "20201101",
        "event_timestamp": timestamp,
        "event_name": event_name,
        "event_bundle_sequence_id": "1001",
        "user_pseudo_id": "1234567890.1234567890",
        "event_params": [
            {"key": "ga_session_id", "value": {"int_value": "1001"}},
            {"key": "engagement_time_msec", "value": {"int_value": "1500"}},
        ],
        "traffic_source": {"source": "google", "medium": "organic", "name": "(not set)"},
        "device": {"category": "desktop", "operating_system": "Windows",
                    "web_info": {"browser": "Chrome"}, "language": "en-us"},
        "geo": {"continent": "Americas", "country": "United States"},
        "ecommerce": {},
        "items": [],
    }


class TestParseJsonDoFn:
    def test_valid_bytes_message(self):
        main, side = run_dofn(ParseJsonDoFn(), json.dumps(valid_event()).encode("utf-8"))
        assert len(main) == 1 and main[0]["event_name"] == "page_view"
        assert side == {}

    def test_valid_str_message(self):
        # ReadFromText in dry-run mode yields str, not bytes
        main, _ = run_dofn(ParseJsonDoFn(), json.dumps(valid_event()))
        assert len(main) == 1

    def test_malformed_json_goes_to_dead_letter(self):
        main, side = run_dofn(ParseJsonDoFn(), b"{not valid json,,")
        assert main == []
        dead = side[ParseJsonDoFn.DEAD_TAG]
        assert len(dead) == 1
        assert dead[0]["error"].startswith("json_parse:")
        assert dead[0]["payload"] == "{not valid json,,"

    def test_non_object_json_goes_to_dead_letter(self):
        main, side = run_dofn(ParseJsonDoFn(), b"[1, 2, 3]")
        assert main == []
        assert ParseJsonDoFn.DEAD_TAG in side


class TestNormalizeEventDoFn:
    def test_coerces_int_fields_from_strings(self):
        event = valid_event()
        main, side = run_dofn(NormalizeEventDoFn(PLACEHOLDERS), event)
        assert side == {}
        assert main[0]["event_timestamp"] == 1604233848000123
        assert main[0]["event_bundle_sequence_id"] == 1001
        assert main[0]["event_params"][0]["value"]["int_value"] == 1001

    def test_nulls_placeholder_values(self):
        event = valid_event()
        event["traffic_source"] = {"source": "(data deleted)", "medium": "<Other>", "name": "(not set)"}
        main, _ = run_dofn(NormalizeEventDoFn(PLACEHOLDERS), event)
        assert main[0]["traffic_source"] == {"source": None, "medium": None, "name": None}

    def test_fills_missing_nested_structures(self):
        event = valid_event()
        event.pop("ecommerce")
        event.pop("items")
        main, _ = run_dofn(NormalizeEventDoFn(PLACEHOLDERS), event)
        # Normalization gives every record the same shape: total_item_quantity
        # is always present (None when missing), items defaults to [].
        assert main[0]["ecommerce"] == {"total_item_quantity": None}
        assert main[0]["items"] == []

    def test_missing_event_date_goes_to_dead_letter(self):
        event = valid_event()
        del event["event_date"]
        main, side = run_dofn(NormalizeEventDoFn(PLACEHOLDERS), event)
        assert main == []
        dead = side[NormalizeEventDoFn.DEAD_TAG]
        assert "event_date" in dead[0]["error"]

    def test_missing_event_name_goes_to_dead_letter(self):
        event = valid_event()
        del event["event_name"]
        main, side = run_dofn(NormalizeEventDoFn(PLACEHOLDERS), event)
        assert main == []
        assert NormalizeEventDoFn.DEAD_TAG in side


class TestClassifyQualityDoFn:
    def test_non_purchase_event_passes_through(self):
        event = valid_event("view_item")
        main, side = run_dofn(ClassifyQualityDoFn(True), event)
        assert len(main) == 1 and side == {}

    def test_purchase_without_transaction_id_is_dropped(self):
        # Normalization turns '(not set)' into None before this stage
        event = valid_event("purchase")
        event["ecommerce"] = {"transaction_id": None, "purchase_revenue_in_usd": 59.0}
        main, side = run_dofn(ClassifyQualityDoFn(True), event)
        assert main == []
        quality = side[ClassifyQualityDoFn.QUALITY_TAG]
        assert quality[0]["rule_name"] == "purchase_without_transaction_id"
        assert quality[0]["action"] == "drop_and_log"

    def test_purchase_with_nonpositive_revenue_is_dropped(self):
        event = valid_event("purchase")
        event["ecommerce"] = {"transaction_id": "AT-002", "purchase_revenue_in_usd": 0.0}
        main, side = run_dofn(ClassifyQualityDoFn(True), event)
        assert main == []
        quality = side[ClassifyQualityDoFn.QUALITY_TAG]
        assert quality[-1]["rule_name"] == "negative_or_zero_revenue"

    def test_purchase_with_null_revenue_is_dropped(self):
        event = valid_event("purchase")
        event["ecommerce"] = {"transaction_id": "AT-003", "purchase_revenue_in_usd": None}
        main, side = run_dofn(ClassifyQualityDoFn(True), event)
        assert main == []
        assert any(r["rule_name"] == "negative_or_zero_revenue"
                   for r in side[ClassifyQualityDoFn.QUALITY_TAG])

    def test_valid_purchase_passes_through(self):
        event = valid_event("purchase")
        event["ecommerce"] = {"transaction_id": "AT-001", "purchase_revenue_in_usd": 129.0}
        main, side = run_dofn(ClassifyQualityDoFn(True), event)
        assert len(main) == 1 and side == {}

    def test_missing_session_id_is_logged_and_kept(self):
        event = valid_event()
        event["event_params"] = []  # no ga_session_id at all
        main, side = run_dofn(ClassifyQualityDoFn(True), event)
        assert len(main) == 1  # kept: use_unknown_dimension
        quality = side[ClassifyQualityDoFn.QUALITY_TAG]
        assert quality[0]["rule_name"] == "missing_session_id"
        assert quality[0]["action"] == "use_unknown_dimension"


class TestDedupeEventsDoFn:
    def test_keeps_first_event_and_logs_duplicates(self):
        first = valid_event(timestamp="1604233900000789")
        dup = valid_event(timestamp="1604233900000789")
        dup["event_bundle_sequence_id"] = "1003"
        main, side = run_dofn(DedupeEventsDoFn(), ("key-1", [first, dup, dict(first)]))
        assert main == [first]
        quality = side[DedupeEventsDoFn.QUALITY_TAG]
        assert quality[0]["affected_rows"] == 2

    def test_single_event_emits_no_quality_record(self):
        event = valid_event()
        main, side = run_dofn(DedupeEventsDoFn(), ("key-1", [event]))
        assert main == [event]
        assert side == {}


class TestLoadQualityConfig:
    def test_reads_rules_from_yaml(self, tmp_path):
        config = tmp_path / "quality_rules.yaml"
        config.write_text(
            "placeholder_values: ['X', '']\n"
            "duplicate_check:\n"
            "  event_key_fields: [user_pseudo_id]\n",
            encoding="utf-8",
        )
        result = load_quality_config(str(config))
        assert result["placeholder_values"] == ["X", ""]
        assert result["event_key_fields"] == ["user_pseudo_id"]

    def test_defaults_when_file_missing(self, tmp_path):
        result = load_quality_config(str(tmp_path / "nope.yaml"))
        assert "user_pseudo_id" in result["event_key_fields"]
        assert "(not set)" in result["placeholder_values"]


class TestEndToEndTransforms:
    def test_full_chain_routes_each_case(self):
        """Parse -> Normalize -> Classify on the fixture scenarios."""
        parse = ParseJsonDoFn()
        normalize = NormalizeEventDoFn(PLACEHOLDERS)
        classify = ClassifyQualityDoFn(True)

        purchase = valid_event("purchase")
        purchase["ecommerce"] = {"transaction_id": "AT-001", "purchase_revenue_in_usd": 129.0}
        bad_purchase = valid_event("purchase")
        bad_purchase["ecommerce"] = {"transaction_id": "(not set)", "purchase_revenue_in_usd": 10.0}

        valid_out, dropped = [], 0
        for raw in [json.dumps(purchase), json.dumps(bad_purchase), "{broken"]:
            main, side = run_dofn(parse, raw.encode("utf-8"))
            if parse.DEAD_TAG in side:
                continue
            for event in main:
                main2, side2 = run_dofn(normalize, event)
                assert side2 == {}
                for normalized_event in main2:
                    main3, side3 = run_dofn(classify, normalized_event)
                    if main3:
                        valid_out.extend(main3)
                    elif ClassifyQualityDoFn.QUALITY_TAG in side3:
                        dropped += 1

        assert len(valid_out) == 1          # the good purchase
        assert dropped == 1                 # the '(not set)' purchase


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
