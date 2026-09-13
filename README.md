# Indian Equity Mutual Fund Factsheet Automation & Comparison

Downloads official monthly factsheets and portfolio disclosures from Indian AMCs, extracts every
equity scheme and its complete holdings, stores each month as an immutable snapshot in PostgreSQL,
and compares any two equity funds on their full portfolios.

The current ingestion universe is the **50 largest open-ended active domestic-equity schemes** in
AMFI's latest official scheme-wise AAUM release. It excludes ELSS/tax-saver funds, ETFs, index and
other passive funds, debt, hybrid/equity-savings/arbitrage funds, multi-asset funds, funds of funds,
gold/silver/commodity funds, solution-oriented funds, and overseas/global funds across every AMC.

---

## ⚡ Quick Deploy (Free)

**Deploy to Render + Vercel in 15 minutes – $0/month**

```bash
# Windows
deploy-setup.bat

# Mac/Linux
bash deploy-setup.sh
```

See [`DEPLOYMENT.md`](./DEPLOYMENT.md) for step-by-step guide.

---

## 1. Requirements

- Python 3.12+ (developed and tested on 3.14)
- Node.js 20+
- Docker Desktop, or any local PostgreSQL 16/17

## 2. Setup

```bash
cd mutual-fund-overlap
cp .env.example .env          # then edit .env

docker compose up -d          # PostgreSQL on 127.0.0.1:5432

cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows;  source .venv/bin/activate elsewhere
pip install -r requirements.txt
alembic upgrade head          # create the schema

cd ../frontend
npm install
```

`.env` keys:

| Key | Meaning |
| --- | --- |
| `DATABASE_URL` | PostgreSQL DSN (`postgresql+psycopg://…`) |
| `GEMINI_API_KEY` | Optional. Everything works without it; only prose and fallback extraction are lost. |
| `GEMINI_MODEL` | Defaults to `gemini-2.5-flash` |
| `DATA_ROOT` | Archive root, defaults to `./data` |
| `ENABLE_EQUITY_ETFS` | Include equity ETFs in the universe |
| `BROWSER_FALLBACK` | Allow Playwright when an AMC page blocks plain HTTP |

The key is read from `.env` only, never logged, and never committed — `.gitignore` excludes `.env`.

## 3. Running

```bash
# API
cd backend && uvicorn app.main:app --reload          # http://localhost:8000/docs

# UI
cd frontend && npm run dev                           # http://localhost:3000
```

## 4. Ingestion

Top-50 acquisition and ingestion (the source manifest records the official URL and the actual month
of every document):

```bash
cd backend
python -m app.ingestion.top50 --target-month 2026-08 --manifest ../data/top50-validated-sources.json
```

The rank is calculated from official AMFI AAUM after consolidating direct/regular plans and options
into their underlying scheme. Holdings are accepted only from a complete official AMC month-end
portfolio workbook. A missing or unreconciled source is reported and is never represented as an
empty portfolio.

Automatic, for the previous calendar month:

```bash
cd backend
python -m app.ingestion.monthly_job
python -m app.ingestion.monthly_job --target-month 2026-08
python -m app.ingestion.monthly_job --amc hdfc --force
```

Manual, for a document already on this PC:

```bash
python -m app.ingestion.cli --amc hdfc  --file "data/raw/2026-07/HDFC/factsheet.pdf"
python -m app.ingestion.cli --amc icici --file "…/factsheet.pdf" --portfolio "…/portfolios.zip"
python -m app.ingestion.cli --amc hdfc  --file "…" --no-gemini --report
```

Exit codes: `0` success, `1` failure, `2` the month is not published yet.

Every run writes `data/reports/YYYY-MM-DD_ingestion_report.{md,json}` with real counts read back
from the database.

### Automatic downloading on this machine

The downloader is domain-pinned to the official AMC hosts, verifies TLS, and checks the SHA-256 of
every archived file. Two environment blockers were observed here and must be cleared before the
scheduled job can fetch anything on its own:

1. **Avast Web/Mail Shield is intercepting HTTPS.** It re-signs `hdfcfund.com` and `icicipruamc.com`
   with `CN=Avast Web/Mail Shield Root`, whose Basic Constraints extension is not marked critical, so
   OpenSSL rejects the chain (`CERTIFICATE_VERIFY_FAILED`). Fix by excluding these domains from
   Avast's HTTPS scanning, or by exporting its root and pointing `SSL_CERT_FILE` at a bundle
   containing it. TLS verification is deliberately never disabled in code.
2. **Playwright's browser must be installed** for the fallback path: `python -m playwright install chromium`.
   Even then HDFC's factsheet page currently answers headless requests with HTTP 403.

Until both are cleared, use the manual CLI above with files downloaded from the AMC sites in a normal
browser — every later stage (parsing, validation, storage, comparison) is identical either way. A run
whose source could not be reached is recorded as `FAILED` with the reason in `error_summary`, never as
`NOT_YET_AVAILABLE`, so a blocked network is never mistaken for an unpublished factsheet.

## 5. Windows Task Scheduler

The factsheet for a month is usually published in the first half of the next month, so the job is
scheduled **daily from the 10th to the 15th** and skips any AMC/month it has already completed.

1. Task Scheduler → **Create Task**, "Run whether user is logged on or not".
2. **Triggers** → New → Monthly → every month → days `10, 11, 12, 13, 14, 15` → start ~07:30.
3. **Actions** → New → Start a program:
   - Program: `C:\…\mutual-fund-overlap\backend\.venv\Scripts\python.exe`
   - Arguments: `-m app.ingestion.monthly_job`
   - Start in: `C:\…\mutual-fund-overlap\backend`
4. **Settings** → allow the task to be run on demand; stop if it runs longer than 2 hours.

Outside that window the job exits immediately unless `--target-month` or `--ignore-window` is given.
Runs are idempotent: repeating one never duplicates a document, snapshot, holding or metric.

## 6. Architecture

```
AMC ─→ Scheme ─→ SchemeMonthlySnapshot ─→ Holding ─→ Security
                         │                              ↑
                         ├─→ SectorAllocation      SecurityAlias
                         └─→ PlanMonthlyMetric
```

```
discover → download → sha256 → archive → parse → classify (equity only)
   → extract holdings → validate → normalise securities → snapshot → report
```

Extraction runs in three levels, in order:

1. **Deterministic** — PDF text, table geometry, AMC-specific rules. Preferred always.
2. **Official portfolio disclosure** — the monthly `.xlsx`/`.zip` disclosure, used when the factsheet
   groups small holdings (ICICI groups everything under 1% of corpus) or prints only a top-10 list.
3. **Gemini** — strict JSON against the Pydantic schema, one retry with validation feedback. It may
   not rename the scheme or change the month.

If all three fail the scheme becomes a `review_item`; nothing is ever invented.

**Gemini never produces a number shown in the UI.** All comparison percentages come from SQL and
`app/comparison/service.py`. Prose commentary is rejected outright if it contains any digit.

### Key rules enforced in code

- Equity classification uses the official product label, never the scheme name. Unclear → `REVIEW_REQUIRED`.
- Unknown values are `NULL`, never `0`, `"N/A"` or `"-"`.
- One holding = one row; no fixed-width stock columns.
- `UNIQUE(scheme_id, as_of_date)` — past months are immutable. A revised PDF becomes a new document
  version and raises a review item rather than overwriting history.
- Securities resolve by ISIN → alias → normalised name. Ambiguity raises `AMBIGUOUS_SECURITY`
  instead of fuzzy-merging two companies.
- Portfolio components must reconcile to 100 ± 0.10, with a per-row rounding allowance.

## 7. Comparison

`GET /api/v1/compare?fund_a_id=&fund_b_id=&as_of_date=&explain=`

| Metric | Meaning |
| --- | --- |
| `a_top10_in_b_pct` | Fund A's top 10 security ids, weighted with **B's** portfolio |
| `b_top10_in_a_pct` | Fund B's top 10 security ids, weighted with **A's** portfolio |
| `common_weight_a_pct` | All common securities as a share of A |
| `common_weight_b_pct` | All common securities as a share of B |
| `symmetric_weighted_overlap_pct` | `Σ min(A, B)` — reported separately from the four above |

The two directional figures are not expected to match. Comparison only ever runs on one month: if
the funds' latest months differ, the latest **common** month is used.

Other endpoints: `/api/v1/funds`, `/api/v1/funds/{id}`, `/api/v1/funds/{id}/holdings`,
`/api/v1/months`, `/health`.

## 8. Tests

```bash
cd backend && .venv\Scripts\python -m pytest -q
```

The test suite includes the mandatory 11-stock example from the specification, which asserts exactly
**74 / 76 / 76 / 81** with a common count of 8.

## 9. Measured results

Against the July 2026 HDFC and ICICI documents in `data/research` (deterministic extraction only,
Gemini disabled):

| Document | Sections | Equity | Stored | Review | Holding rows |
| --- | --- | --- | --- | --- | --- |
| HDFC factsheet | 53 | 22 | 22 | 0 | 1,512 |
| HDFC index factsheet | 51 | 36 | 23 | 13 | 652 |
| ICICI factsheet (+ portfolio zip) | 79 | 33 | 29 | 4 | 1,961 |

Totals: **74 comparable equity schemes, 4,125 holding rows, 854 unique securities, 44 open review
items.** The review items are genuine gaps, not failures to hide: HDFC's index factsheet prints only
a top-10 list per scheme (its per-scheme portfolio disclosures fill this in a real scheduled run),
two ICICI schemes are absent from that month's disclosure archive, and 13 sections carry no product
label clear enough to classify.

## 10. Layout

```
backend/app/
  api/            funds + compare endpoints
  comparison/     deterministic overlap engine
  db/             SQLAlchemy models and session
  downloaders/    per-AMC discovery and download (domain-pinned, hash-verified)
  extraction/     deterministic rules, Gemini client, fallback orchestrator
  ingestion/      pipeline, CLI, monthly job, persistence, reports
  normalization/  security identity and industries
  parsers/        HDFC, ICICI, portfolio workbooks
  schemas/        Pydantic contracts shared by every parser
  validation/     equity classification and portfolio reconciliation
data/             raw/ extracted/ rejected/ reports/ logs/  (never overwritten)
frontend/         Next.js comparison UI
```
