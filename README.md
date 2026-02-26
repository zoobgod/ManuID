# ManuID

ManuID is a secure procurement intelligence web app for pharmaceutical procurement teams.
It lets managers search vendors by pharmacopeia product type, ingest new vendor sources from approved websites, and verify supplier records.

## Stack

- Backend API: FastAPI + SQLAlchemy
- Frontend: Streamlit
- DB: SQLite by default (`manuid.db`), PostgreSQL-ready via `DATABASE_URL`
- Scraping: `httpx` + `BeautifulSoup` with strict allowlist and SSRF protections
- Optional AI enrichment: OpenAI API (disabled by default)

## What this app provides

- Product-type search (USP/EP/BP/JP categories and custom product types)
- Vendor directory with contact info and procurement metadata
- URL-based ingestion pipeline for vendor-list pages
- Evidence tracking (`source_records`, `company_evidences`) for auditability
- Manual verification workflow (`UNVERIFIED`, `AUTO_VERIFIED`, `HUMAN_VERIFIED`)
- API-key auth + rate limiting + domain allowlist

## APIs included

Base URL: `http://127.0.0.1:8000`

- `GET /health`
- `GET /v1/product-types`
- `POST /v1/search/vendors`
- `POST /v1/ingestion/url`
- `GET /v1/vendors/{vendor_id}`
- `POST /v1/vendors/{vendor_id}/verify`
- `GET /v1/source-catalog`

Auth header:

```bash
Authorization: Bearer <API_KEY>
```

## Source websites configured (initial catalog)

These are preloaded as reference sources and allowed by default in `.env.example`:

- `https://www.sigmaaldrich.com`
- `https://www.spectrumchemical.com`
- `https://www.fishersci.com`
- `https://www.avantorsciences.com`
- `https://www.tcichemicals.com`

You can add/remove domains in `SCRAPE_ALLOWLIST`.

## Database model

Core entities:

- `product_types`
- `companies`
- `contacts`
- `company_product_types`
- `source_records`
- `company_evidences`

This supports both curated data and parser-ingested evidence with confidence scoring.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Initialize DB:

```bash
python scripts/init_db.py
```

Run API:

```bash
./scripts/run_api.sh
```

Run Streamlit UI (new terminal):

```bash
./scripts/run_streamlit.sh
```

Open: `http://localhost:8501`

Use API key from `.env` (default: `dev-key-change-me`).

## Security controls

- API key auth required for all `/v1/*` endpoints
- In-memory per-key/IP rate limiting
- Scraping only from `SCRAPE_ALLOWLIST`
- SSRF guard blocks localhost/private IP targets
- HTML size and timeout limits
- Pydantic validation on all API payloads

## Optional OpenAI enrichment

If you want metadata extraction from unstructured source text:

1. Set `OPENAI_API_KEY` in `.env`
2. Set `ENABLE_OPENAI_ENRICHMENT=true`

The app will try to enrich certifications/regions/MOQ/lead-time from parsed text.

## Tests

```bash
API_KEYS=test-key DATABASE_URL=sqlite:///./test_manuid.db SCRAPE_ALLOWLIST=example.com pytest -q
```

## Notes

- This MVP intentionally separates `UNVERIFIED` vs verified data for procurement safety.
- Always review vendor data before procurement decisions.
