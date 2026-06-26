"""Lead enrichment via the BatchData and US Census Bureau APIs.

Both lookups are keyed on the lead's ZIP code. Network/credential failures are
caught and surfaced as ``{"error": ...}`` so a single bad lead never crashes the
batch run.
"""
import logging
import os

import requests

logger = logging.getLogger(__name__)

BATCHDATA_URL = "https://api.batchdata.com/api/v1/property/search"
# Census ACS 5-year: median household income (B19013_001E) + population (B01003_001E)
CENSUS_URL = "https://api.census.gov/data/2022/acs/acs5"

REQUEST_TIMEOUT = 15  # seconds


def _real_key(env_name: str):
    """Return the env var only if it's a usable key (not blank/placeholder)."""
    value = (os.environ.get(env_name) or "").strip()
    if not value or value.upper() == "PLACEHOLDER":
        return None
    return value


def enrich_lead(lead: dict) -> dict:
    """Enrich a single lead with property + demographic data from its ZIP code.

    Returns a new dict: the original lead plus an ``enrichment`` key holding
    ``property`` and ``demographics`` sub-dicts.
    """
    zip_code = str(
        lead.get("Zip Code") or lead.get("zip_code") or lead.get("zip") or ""
    ).strip()
    enrichment = {
        "zip_code": zip_code,
        "property": get_property_data(zip_code),
        "demographics": get_census_data(zip_code),
    }
    return {**lead, "enrichment": enrichment}


def get_property_data(zip_code: str) -> dict:
    """Look up aggregate property data for a ZIP code via the BatchData API."""
    api_key = _real_key("BATCHDATA_API_KEY")
    if not zip_code:
        return {"error": "missing zip_code"}
    if not api_key:
        # BatchData has no keyless mode — skip the doomed request entirely.
        return {"error": "BATCHDATA_API_KEY not configured"}

    try:
        resp = requests.post(
            BATCHDATA_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"searchCriteria": {"query": zip_code}, "options": {"take": 10}},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", {}) if isinstance(data, dict) else {}
        properties = results.get("properties", []) if isinstance(results, dict) else []
        return {
            "result_count": len(properties),
            "properties": properties[:10],
        }
    except requests.RequestException as exc:
        logger.error("BatchData lookup failed for %s: %s", zip_code, exc)
        return {"error": str(exc)}


def get_census_data(zip_code: str) -> dict:
    """Look up demographics for a ZIP code via the US Census Bureau ACS API.

    Uses the ZIP Code Tabulation Area (ZCTA) geography.
    """
    if not zip_code:
        return {"error": "missing zip_code"}

    params = {
        "get": "NAME,B19013_001E,B01003_001E",
        "for": f"zip code tabulation area:{zip_code}",
    }
    # The Census API requires a key — without one it returns a "missing key"
    # HTML page (not JSON). Skip the doomed request when no real key is set.
    api_key = _real_key("CENSUS_API_KEY")
    if not api_key:
        return {"error": "CENSUS_API_KEY not configured"}
    params["key"] = api_key

    try:
        resp = requests.get(CENSUS_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        rows = resp.json()
        # Census returns [header_row, data_row]; bail if no data row.
        if not isinstance(rows, list) or len(rows) < 2:
            return {"error": "no census data for zip"}
        header, values = rows[0], rows[1]
        record = dict(zip(header, values))
        return {
            "name": record.get("NAME"),
            "median_household_income": _to_int(record.get("B19013_001E")),
            "population": _to_int(record.get("B01003_001E")),
        }
    except requests.RequestException as exc:
        logger.error("Census lookup failed for %s: %s", zip_code, exc)
        return {"error": str(exc)}


def _to_int(value):
    """Census returns numeric fields as strings; coerce, tolerating junk."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
