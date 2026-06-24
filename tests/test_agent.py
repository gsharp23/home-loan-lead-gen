"""Basic unit tests for each pipeline module.

All external services — Google Sheets, BatchData, the Census Bureau, Claude, and
ChromaDB — are mocked, so these run offline with no credentials.

Run with:  pytest -q
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent import enrich, main, outreach, rag, scorer


def _text_response(text: str):
    """Build a fake Anthropic response whose single text block is `text`."""
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


SAMPLE_LEAD = {
    "first_name": "Jordan",
    "zip_code": "30301",
    "loan_amount": 250000,
    "credit_score": 640,
    "income": 72000,
    "property_type": "single-family",
    "first_time_buyer": "yes",
}


# --------------------------------------------------------------------------- #
# enrich.py
# --------------------------------------------------------------------------- #
def test_get_property_data_success():
    fake = MagicMock(status_code=200)
    fake.json.return_value = {"results": {"properties": [{"id": 1}, {"id": 2}]}}
    fake.raise_for_status.return_value = None
    with patch.dict("os.environ", {"BATCHDATA_API_KEY": "k"}), patch.object(
        enrich.requests, "post", return_value=fake
    ):
        result = enrich.get_property_data("30301")
    assert result["result_count"] == 2


def test_get_property_data_missing_zip():
    assert "error" in enrich.get_property_data("")


def test_get_census_data_success():
    fake = MagicMock(status_code=200)
    fake.json.return_value = [
        ["NAME", "B19013_001E", "B01003_001E", "zip code tabulation area"],
        ["ZCTA5 30301", "65000", "12000", "30301"],
    ]
    fake.raise_for_status.return_value = None
    with patch.object(enrich.requests, "get", return_value=fake):
        result = enrich.get_census_data("30301")
    assert result["median_household_income"] == 65000
    assert result["population"] == 12000


def test_enrich_lead_combines_sources():
    with patch.object(enrich, "get_property_data", return_value={"result_count": 1}), patch.object(
        enrich, "get_census_data", return_value={"population": 100}
    ):
        out = enrich.enrich_lead(SAMPLE_LEAD)
    assert out["enrichment"]["property"]["result_count"] == 1
    assert out["enrichment"]["demographics"]["population"] == 100
    assert out["first_name"] == "Jordan"  # original fields preserved


# --------------------------------------------------------------------------- #
# rag.py
# --------------------------------------------------------------------------- #
def test_load_program_documents_reads_programs():
    docs = rag.load_program_documents("programs")
    assert docs, "expected at least one chunk from programs/"
    programs = {d.metadata.get("program") for d in docs}
    assert {"fha", "usda", "state_programs"} <= programs


def test_lead_to_query_includes_zip():
    query = rag._lead_to_query(SAMPLE_LEAD)
    assert "30301" in query


def test_match_programs_uses_store():
    fake_store = MagicMock()
    fake_store.similarity_search.return_value = [
        SimpleNamespace(metadata={"program": "fha"}, page_content="FHA details"),
        SimpleNamespace(metadata={"program": "usda"}, page_content="USDA details"),
    ]
    matches = rag.match_programs(SAMPLE_LEAD, k=2, store=fake_store)
    assert [m["program"] for m in matches] == ["fha", "usda"]
    fake_store.similarity_search.assert_called_once()


# --------------------------------------------------------------------------- #
# scorer.py
# --------------------------------------------------------------------------- #
def test_score_lead_parses_json():
    client = MagicMock()
    client.messages.create.return_value = _text_response(
        json.dumps({"score": 8, "rationale": "Strong credit and income."})
    )
    result = scorer.score_lead(SAMPLE_LEAD, client=client)
    assert result["score"] == 8
    assert "credit" in result["rationale"].lower()


def test_score_lead_clamps_out_of_range():
    client = MagicMock()
    client.messages.create.return_value = _text_response(
        json.dumps({"score": 99, "rationale": "too high"})
    )
    assert scorer.score_lead(SAMPLE_LEAD, client=client)["score"] == 10


def test_score_lead_handles_bad_json():
    client = MagicMock()
    client.messages.create.return_value = _text_response("not json")
    result = scorer.score_lead(SAMPLE_LEAD, client=client)
    assert result["score"] == 0


# --------------------------------------------------------------------------- #
# outreach.py
# --------------------------------------------------------------------------- #
def test_write_outreach_returns_message():
    client = MagicMock()
    client.messages.create.return_value = _text_response(
        "Hi Jordan! You may qualify for an FHA loan — happy to walk you through it."
    )
    msg = outreach.write_outreach(
        SAMPLE_LEAD,
        [{"program": "fha", "content": "FHA details"}],
        client=client,
    )
    assert "Jordan" in msg
    # The matched program name should be passed into the prompt.
    sent = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "fha" in sent


# --------------------------------------------------------------------------- #
# main.py
# --------------------------------------------------------------------------- #
def test_read_new_leads_filters_processed():
    worksheet = MagicMock()
    worksheet.get_all_records.return_value = [
        {"first_name": "A", "processed": ""},
        {"first_name": "B", "processed": "yes"},
        {"first_name": "C"},
    ]
    leads = main.read_new_leads(worksheet)
    names = [lead["first_name"] for lead in leads]
    assert names == ["A", "C"]
    assert leads[0]["_row"] == 2  # header is row 1


def test_process_lead_runs_pipeline():
    lead = {**SAMPLE_LEAD, "_row": 5}
    with patch.object(main, "enrich_lead", side_effect=lambda x: {**x, "enrichment": {}}), patch.object(
        main, "match_programs", return_value=[{"program": "fha", "content": "x"}]
    ), patch.object(
        main, "score_lead", return_value={"score": 7, "rationale": "ok"}
    ), patch.object(
        main, "write_outreach", return_value="Hi Jordan!"
    ):
        result = main.process_lead(lead, store=MagicMock())
    assert result["row"] == 5
    assert result["score"] == 7
    assert result["programs"] == ["fha"]
    assert result["outreach"] == "Hi Jordan!"


def test_lambda_handler_returns_summary():
    with patch.object(main, "run", return_value={"processed": 3, "results": []}):
        resp = main.lambda_handler({}, None)
    assert resp == {"statusCode": 200, "processed": 3}
