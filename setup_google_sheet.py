"""One-time setup: create the "Home Loan Leads" Google Sheet via gspread OAuth.

You authorize as *yourself* (a normal Google account) — no service account is
used for this step. gspread opens a browser once, you approve, and the token is
cached locally so future runs don't prompt.

After creating the sheet, the script shares it with the runtime service account
(read from credentials.json, if present) so the daily Lambda agent can read it.

Prerequisites (one-time, in the Google Cloud project):
  1. Enable the Google Sheets API and Google Drive API.
  2. Create an OAuth client of type "Desktop app" and download its JSON.
  3. Save that JSON as  oauth_credentials.json  in this folder.

Run it:
    python3 setup_google_sheet.py
"""
import json
import os
import sys

import gspread

SHEET_NAME = os.environ.get("GOOGLE_SHEET_NAME", "Home Loan Leads")

# OAuth client secrets you download from Google Cloud ("Desktop app").
OAUTH_CREDENTIALS = "oauth_credentials.json"
# Token cache written after you authorize once (gitignored — never commit).
AUTHORIZED_USER = "oauth_authorized_user.json"
# Runtime service account the Lambda agent uses; we share the sheet with it.
SERVICE_ACCOUNT_FILE = "credentials.json"

# Header row. Columns C/E/F/G/H match the README's Zapier field mapping;
# the trailing columns are what agent/main.py writes back per lead.
HEADERS = [
    "Created At",    # A
    "Lead Source",   # B
    "Name",          # C  <- Zapier full_name
    "First Name",    # D
    "Phone",         # E  <- Zapier phone_number
    "Email",         # F  <- Zapier email
    "Location",      # G  <- Zapier zip_code
    "Price Range",   # H  <- Zapier budget
    "score",         # I  <- agent writeback
    "programs",      # J  <- agent writeback
    "outreach",      # K  <- agent writeback
    "processed",     # L  <- agent writeback (blank = new lead)
]

SETUP_HELP = f"""
Missing OAuth client credentials: {OAUTH_CREDENTIALS}

gspread OAuth needs a "Desktop app" OAuth client. One-time steps in the
Google Cloud project (lead-gen-agent-500600):

  1. Enable APIs:
       APIs & Services -> Library -> enable "Google Sheets API"
                                      enable "Google Drive API"
  2. OAuth consent screen:
       APIs & Services -> OAuth consent screen
         - User type: External -> Create
         - Fill app name + your email, Save & Continue through the steps
         - Add yourself under "Test users"
  3. Create the client:
       APIs & Services -> Credentials -> Create Credentials
         -> OAuth client ID -> Application type: "Desktop app" -> Create
         -> Download JSON
  4. Save that file here as:
       {os.path.abspath(OAUTH_CREDENTIALS)}

Then run again:  python3 setup_google_sheet.py
"""


def main() -> int:
    if not os.path.exists(OAUTH_CREDENTIALS):
        print(SETUP_HELP)
        return 1

    # Authorize as yourself (opens a browser the first time; cached afterward).
    gc = gspread.oauth(
        credentials_filename=OAUTH_CREDENTIALS,
        authorized_user_filename=AUTHORIZED_USER,
    )

    # Create the sheet, or reuse it if it already exists.
    try:
        sh = gc.open(SHEET_NAME)
        print(f"Sheet already exists: {SHEET_NAME}")
    except gspread.SpreadsheetNotFound:
        sh = gc.create(SHEET_NAME)
        print(f"Created sheet: {SHEET_NAME}")

    ws = sh.sheet1
    if ws.row_values(1) != HEADERS:
        ws.update([HEADERS], "A1")
        ws.freeze(rows=1)
        print(f"Wrote header row ({len(HEADERS)} columns).")
    else:
        print("Header row already in place.")

    # Share with the runtime service account so the agent can read/write.
    if os.path.exists(SERVICE_ACCOUNT_FILE):
        try:
            sa_email = json.load(open(SERVICE_ACCOUNT_FILE)).get("client_email")
        except (OSError, json.JSONDecodeError):
            sa_email = None
        if sa_email:
            sh.share(sa_email, perm_type="user", role="writer")
            print(f"Shared with service account: {sa_email}")
    else:
        print(f"(No {SERVICE_ACCOUNT_FILE} found — skipping service-account share.)")

    print(f"\nDone. Spreadsheet URL:\n  {sh.url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
