"""Orchestrator + AWS Lambda entrypoint for the home-loan lead-gen pipeline.

How leads enter the system (upstream of this module):

    Meta Lead Ads (Facebook + Instagram)
        -> a prospect submits a lead form
    Zapier
        -> Trigger: Meta Lead Ads "New Lead"
        -> normalizes the form fields into the sheet columns
           (Name, Phone, Email, Zip Code, Budget)
        -> Action: Google Sheets "Create Row" in the "Home Loan Leads" sheet
    Google Sheets ("Home Loan Leads")
        -> each new submission becomes a new row

This Lambda agent runs daily (07:00 UTC via EventBridge) and picks up from
there: it reads the new rows Zapier created, then for each lead runs
enrich -> match programs -> score -> draft outreach. Results are written back
to the sheet and returned in the handler's summary.
"""
import json
import logging
import os

import gspread
from dotenv import load_dotenv

from agent.enrich import enrich_lead
from agent.outreach import write_outreach
from agent.rag import get_store, match_programs
from agent.scorer import score_lead

load_dotenv()

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

SHEET_NAME = os.environ.get("GOOGLE_SHEET_NAME", "Home Loan Leads")
# OAuth (user-account) auth — matches how the sheet was created via
# setup_google_sheet.py. These default to the project-local token files; override
# with env vars if you keep them at the gspread default (~/.config/gspread/).
OAUTH_CREDENTIALS = os.environ.get("GSPREAD_OAUTH_CREDENTIALS", "oauth_credentials.json")
OAUTH_AUTHORIZED_USER = os.environ.get("GSPREAD_OAUTH_AUTHORIZED_USER", "oauth_authorized_user.json")
# Sheet column headers (must match row 1 of "Home Loan Leads" exactly).
# A lead is "new" when its Status cell is empty/falsey.
STATUS_COLUMN = "Status"
COL_SCORE = "Score"
COL_OUTREACH = "Outreach Draft"
COL_PROGRAMS = "Programs Matched"
COL_ENRICHMENT = "Enrichment Data"


def get_worksheet(sheet_name: str = SHEET_NAME):
    """Authenticate as the user via gspread OAuth and open the first worksheet."""
    client = gspread.oauth(
        credentials_filename=OAUTH_CREDENTIALS,
        authorized_user_filename=OAUTH_AUTHORIZED_USER,
    )
    return client.open(sheet_name).sheet1


def read_new_leads(worksheet) -> list[dict]:
    """Return rows that have not yet been processed, each tagged with its row index."""
    records = worksheet.get_all_records()  # list of dicts keyed by header
    new_leads = []
    for i, row in enumerate(records, start=2):  # row 1 is the header
        if not str(row.get(STATUS_COLUMN, "")).strip():
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
        "enrichment": enriched.get("enrichment", {}),
    }


def write_result(worksheet, result: dict) -> None:
    """Write the results back into the lead's row, best-effort.

    Maps to the sheet's columns: Score, Status, Outreach Draft,
    Programs Matched, Enrichment Data. Setting Status marks the lead processed
    so it isn't picked up again on the next run.
    """
    row = result.get("row")
    if not row:
        return
    headers = worksheet.row_values(1)

    def col(name: str):
        return headers.index(name) + 1 if name in headers else None

    updates = {
        COL_SCORE: result["score"],
        STATUS_COLUMN: "Processed",
        COL_OUTREACH: result["outreach"],
        COL_PROGRAMS: ", ".join(result["programs"]),
        COL_ENRICHMENT: json.dumps(result.get("enrichment", {}), default=str),
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
