"""Orchestrator + AWS Lambda entrypoint for the home-loan lead-gen pipeline.

Reads new rows from a Google Sheet, then for each lead: enrich -> match programs
-> score -> draft outreach. Results are written back to the sheet and returned in
the handler's summary.
"""
import logging
import os

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

from agent.enrich import enrich_lead
from agent.outreach import write_outreach
from agent.rag import get_store, match_programs
from agent.scorer import score_lead

load_dotenv()

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

SHEET_NAME = os.environ.get("GOOGLE_SHEET_NAME", "Home Loan Leads")
CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]
# A lead is "new" when this column is empty/falsey.
PROCESSED_COLUMN = "processed"


def get_worksheet(sheet_name: str = SHEET_NAME):
    """Authenticate with a service account and open the first worksheet."""
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open(sheet_name).sheet1


def read_new_leads(worksheet) -> list[dict]:
    """Return rows that have not yet been processed, each tagged with its row index."""
    records = worksheet.get_all_records()  # list of dicts keyed by header
    new_leads = []
    for i, row in enumerate(records, start=2):  # row 1 is the header
        if not str(row.get(PROCESSED_COLUMN, "")).strip():
            new_leads.append({**row, "_row": i})
    logger.info("Found %d new lead(s) in '%s'", len(new_leads), SHEET_NAME)
    return new_leads


def process_lead(lead: dict, store=None) -> dict:
    """Run the full pipeline for one lead and return the result record."""
    enriched = enrich_lead(lead)
    programs = match_programs(enriched, store=store)
    scoring = score_lead(enriched)
    message = write_outreach(enriched, programs)
    return {
        "row": lead.get("_row"),
        "score": scoring["score"],
        "rationale": scoring["rationale"],
        "programs": sorted({p["program"] for p in programs}),
        "outreach": message,
    }


def write_result(worksheet, result: dict) -> None:
    """Write the score/programs/outreach back to the lead's row, best-effort."""
    row = result.get("row")
    if not row:
        return
    headers = worksheet.row_values(1)

    def col(name: str):
        return headers.index(name) + 1 if name in headers else None

    updates = {
        "score": result["score"],
        "programs": ", ".join(result["programs"]),
        "outreach": result["outreach"],
        PROCESSED_COLUMN: "yes",
    }
    for name, value in updates.items():
        c = col(name)
        if c:
            worksheet.update_cell(row, c, value)


def run() -> dict:
    """Process all new leads. Returns a summary dict."""
    worksheet = get_worksheet()
    leads = read_new_leads(worksheet)
    store = get_store()  # build/open the RAG index once for the whole batch

    results = []
    for lead in leads:
        try:
            result = process_lead(lead, store=store)
            write_result(worksheet, result)
            results.append(result)
        except Exception:  # one bad lead shouldn't sink the batch
            logger.exception("Failed to process row %s", lead.get("_row"))

    return {"processed": len(results), "results": results}


def lambda_handler(event, context):
    """AWS Lambda entrypoint — invoked daily by EventBridge."""
    summary = run()
    logger.info("Run complete: processed %d lead(s)", summary["processed"])
    return {"statusCode": 200, "processed": summary["processed"]}


if __name__ == "__main__":
    print(run())
