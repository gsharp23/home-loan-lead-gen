# home-loan-lead-gen

An AI-powered lead-generation pipeline for home-loan originators. New leads land
in a Google Sheet; the agent enriches each one with property and demographic
data, scores it 1–10 with Claude, matches it to the loan programs it likely
qualifies for (via a local RAG index of program docs), and drafts a personalized
outreach text message. The pipeline runs daily on AWS Lambda, triggered by an
EventBridge cron at 7:00 AM UTC.

## What it does

1. **Ingest** — read new rows from a Google Sheet with `gspread` + a service account.
2. **Enrich** — look up property data (BatchData API) and demographics (US Census
   Bureau API) from each lead's ZIP code.
3. **Match** — retrieve relevant loan programs from a local ChromaDB vector store
   built from the Markdown docs in `programs/` (loaded via LangChain).
4. **Score** — ask Claude Sonnet to rate each enriched lead 1–10.
5. **Outreach** — ask Claude Sonnet to write a personalized SMS that names the
   matching programs.

## Stack

| Layer | Tech |
| --- | --- |
| Language | Python 3.11 |
| LLM | Claude Sonnet (`claude-sonnet-4-6`) via the `anthropic` SDK |
| Lead source | Google Sheets (`gspread`, service account `credentials.json`) |
| Enrichment | BatchData API, US Census Bureau API (`requests`) |
| RAG | ChromaDB + LangChain (local, on-disk vector store) |
| Config | `python-dotenv` (`.env`) |
| Infra | AWS Lambda + EventBridge (Terraform) |

## Architecture

```
                         ┌──────────────────────┐
   EventBridge cron      │   AWS Lambda          │
   (daily 07:00 UTC) ───▶│   agent/main.py       │
                         │   lambda_handler()    │
                         └───────────┬───────────┘
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        ▼                            ▼                             ▼
  Google Sheets               Enrichment APIs               Claude Sonnet
  (gspread)                   BatchData + Census             scorer + outreach
        │                            │                             │
        │   new rows                 │  property + demographics    │  score 1-10
        └──────────────┬─────────────┘                             │  + SMS draft
                       ▼                                            │
              enriched lead ──▶ RAG match (ChromaDB / programs/) ───┘
                       │
                       ▼
            results written back / logged
```

Each module is independently importable and unit-testable:

| Module | Responsibility |
| --- | --- |
| `agent/main.py` | Orchestrator + Lambda handler. Reads new Sheet rows, runs the pipeline per lead. |
| `agent/enrich.py` | BatchData + Census Bureau lookups keyed on ZIP. |
| `agent/rag.py` | Build/query the ChromaDB index from `programs/*.md` via LangChain. |
| `agent/scorer.py` | Claude Sonnet call → integer score 1–10 + rationale. |
| `agent/outreach.py` | Claude Sonnet call → personalized outreach SMS naming matched programs. |

## Setup

1. **Clone & create a virtualenv**

   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure secrets**

   ```bash
   cp .env.example .env
   # then edit .env and fill in your keys
   ```

   | Variable | Purpose |
   | --- | --- |
   | `ANTHROPIC_API_KEY` | Claude API (scoring + outreach) |
   | `BATCHDATA_API_KEY` | BatchData property enrichment |
   | `CENSUS_API_KEY` | US Census Bureau demographics |
   | `GOOGLE_SHEET_NAME` | Name of the leads spreadsheet (default `Home Loan Leads`) |
   | `AWS_REGION` | Region for the deployed Lambda (default `us-east-1`) |

3. **Google service account**

   Create a Google Cloud service account with the Sheets API enabled, download
   its key as `credentials.json` in the project root, and share the spreadsheet
   with the service account's email. `credentials.json` is gitignored.

4. **Build the RAG index** (first run does this automatically; to pre-build):

   ```bash
   python -c "from agent.rag import build_index; build_index()"
   ```

5. **Run locally**

   ```bash
   python -m agent.main
   ```

## Testing

```bash
pytest -q
```

Tests mock all external services (Google Sheets, BatchData, Census, Claude,
ChromaDB) so they run offline with no credentials.

## Deploy (Terraform)

The `terraform/` config provisions the Lambda function and an EventBridge rule
that invokes it daily at 7:00 AM UTC.

```bash
cd terraform
terraform init
terraform apply
```

> Package the code (`agent/`, `programs/`, and dependencies) into the deployment
> zip your Lambda expects — see `terraform/lambda.tf` for the `filename` /
> handler it references. Dependencies are typically shipped as a Lambda layer.
