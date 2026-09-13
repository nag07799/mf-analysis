# System Architecture

## Deployment Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        INTERNET / USERS                           │
└──────────────────────────────────────────────────────────────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    │                           │
            ┌───────▼────────┐         ┌───────▼────────┐
            │  Vercel CDN    │         │   Render Edge  │
            │  (Frontend)    │         │   (API Gateway)│
            └────────┬───────┘         └────────┬───────┘
                     │                          │
            ┌────────▼──────────┐      ┌────────▼──────────┐
            │ Next.js App       │      │ FastAPI Backend   │
            │ (React, TypeScript)       │ (Python, FastAPI) │
            │                   │      │                   │
            │ ✓ Fund Selector   │      │ ✓ API Endpoints   │
            │ ✓ Comparison UI   │      │ ✓ Business Logic  │
            │ ✓ Charts/Tables   │      │ ✓ Fund Matching   │
            │ ✓ Share Results   │      │ ✓ Portfolio Calc  │
            └────────┬──────────┘      └────────┬──────────┘
                     │                          │
                     └──────────────┬───────────┘
                                    │
                         (HTTPS / REST API)
                                    │
                     ┌──────────────▼───────────────┐
                     │  Render PostgreSQL Database  │
                     │                              │
                     │ ✓ Schemes (123 funds)        │
                     │ ✓ Holdings (7,565 total)     │
                     │ ✓ Securities (1,161 unique)  │
                     │ ✓ Monthly Snapshots          │
                     │ ✓ Comparison History         │
                     └──────────────────────────────┘
```

## Data Flow: Monthly Ingestion

```
┌──────────────────────────────────────────────────────────────┐
│            MONTHLY AUTOMATIC DATA INGESTION                  │
│                  (Render Cron or GitHub)                     │
└──────────────────────────────────────────────────────────────┘
                           │
                ┌──────────▼──────────┐
                │ STEP 1: Fetch Rank  │
                │                     │
                │ AMFI API            │
                │ ↓ Top 50 funds      │
                │ ↓ Ranked by AUM     │
                └──────────┬──────────┘
                           │
                ┌──────────▼────────────────────┐
                │ STEP 2: Discover Portfolios   │
                │                               │
                │ For each fund house:          │
                │ ├─ HDFC (Config-driven HTTP) │
                │ ├─ ICICI (Playwright JS)     │
                │ ├─ Nippon (Config-driven)    │
                │ ├─ Motilal (Playwright)      │
                │ ├─ Tata (Config-driven)      │
                │ ├─ Others                    │
                │ ↓ Download workbooks         │
                └──────────┬────────────────────┘
                           │
                ┌──────────▼──────────────────┐
                │ STEP 3: Parse Holdings      │
                │                             │
                │ Universal Portfolio Parser: │
                │ ├─ XLSX (OpenPyXL)         │
                │ ├─ XLS (xlrd, legacy)      │
                │ ├─ CSV/Text                │
                │ ↓ Extract 123 funds        │
                │ ↓ 7,565 holdings           │
                └──────────┬──────────────────┘
                           │
                ┌──────────▼──────────────────┐
                │ STEP 4: Validate Data       │
                │                             │
                │ ✓ Weight totals (±0.1%)     │
                │ ✓ ISIN lookups              │
                │ ✓ Company name matching     │
                │ ✓ Duplicate detection       │
                └──────────┬──────────────────┘
                           │
                ┌──────────▼──────────────────┐
                │ STEP 5: Normalize & Store   │
                │                             │
                │ ✓ Security ID matching      │
                │ ✓ Industry classification   │
                │ ✓ Insert monthly snapshot   │
                │ ✓ Link to scheme            │
                │ ✓ Record holdings           │
                └──────────┬──────────────────┘
                           │
                ┌──────────▼──────────────────┐
                │ STEP 6: Generate Report     │
                │                             │
                │ ✓ Ingestion counts         │
                │ ✓ Error summary            │
                │ ✓ Processing time          │
                │ ✓ Save as JSON + Markdown  │
                └──────────────────────────────┘
```

## Data Flow: User Comparison

```
┌───────────────────────────────────────────────┐
│         USER OPENS COMPARISON UI              │
│        (Vercel Frontend / Browser)            │
└───────────────────────────────────────────────┘
                      │
                      │ Page Loads
                      ▼
        ┌─────────────────────────────┐
        │ Load Available Funds & Dates │
        │ GET /api/v1/funds           │
        │ GET /api/v1/available-dates │
        └──────────┬──────────────────┘
                   │
                   ▼ (User selects Fund A, Fund B, Date)
        ┌─────────────────────────────┐
        │ Fetch Comparison Data       │
        │ GET /api/v1/compare         │
        └──────────┬──────────────────┘
                   │
        ┌──────────▼──────────────────┐
        │ Backend Calculation:        │
        │                             │
        │ 1. Load Fund A portfolio    │
        │    (123 holdings)           │
        │ 2. Load Fund B portfolio    │
        │    (60 holdings)            │
        │ 3. Calculate metrics:       │
        │    ├─ Top 10 totals         │
        │    ├─ A's Top 10 in B (%)   │
        │    ├─ B's Top 10 in A (%)   │
        │    ├─ Common stocks (%)     │
        │    └─ Overlap stats         │
        │ 4. Return structured JSON   │
        └──────────┬──────────────────┘
                   │
        ┌──────────▼──────────────────┐
        │ Frontend Renders:           │
        │                             │
        │ ✓ Fund A info              │
        │ ✓ Fund B info              │
        │ ✓ Comparison metrics       │
        │ ✓ Top 10 tables            │
        │ ✓ Common holdings table    │
        │ ✓ Charts & visualizations  │
        └─────────────────────────────┘
```

## Database Schema (Simplified)

```
┌─────────────┐
│   SCHEME    │ (123 equity funds)
├─────────────┤
│ id          │
│ amc_id ─────┼──► AMC table
│ name        │
│ category    │
│ status      │
└──────┬──────┘
       │ 1:M
       │
┌──────▼─────────────────┐
│ SCHEME_MONTHLY_SNAPSHOT │ (Monthly data)
├─────────────────────────┤
│ id                      │
│ scheme_id ──────────────┼──► SCHEME
│ as_of_date              │
│ aum_crore               │
│ equity_pct              │
│ reit_pct                │
│ cash_pct                │
└──────┬────────────────┬─┘
       │ 1:M            │
       │                │ FK
       │                ▼
       │            ┌──────────┐
       │            │ DOCUMENT │
       │            │ (source) │
       │            └──────────┘
       │
┌──────▼──────────────┐
│     HOLDING        │ (7,565 individual holdings)
├────────────────────┤
│ id                 │
│ snapshot_id ───────┼──► SCHEME_MONTHLY_SNAPSHOT
│ security_id ───────┼──► SECURITY
│ weight_pct         │
│ market_value_crore │
└────────────────────┘
       │
       │ FK
       ▼
┌─────────────────┐
│   SECURITY      │ (1,161 unique securities)
├─────────────────┤
│ id              │
│ canonical_name  │
│ isin            │
│ nse_symbol      │
│ type (EQUITY)   │
└─────────────────┘
```

## Component Interactions

### Backend (FastAPI)

```
┌─────────────────────────────────────────────────┐
│         FastAPI Application                     │
├─────────────────────────────────────────────────┤
│ app/main.py                                     │
│ ├─ Health Check Endpoint                       │
│ └─ CORS Middleware                             │
│                                                 │
│ app/api/                                        │
│ ├─ funds.py        → GET /api/v1/funds        │
│ ├─ compare.py      → GET /api/v1/compare      │
│ └─ (More endpoints)                            │
│                                                 │
│ app/comparison/    → Comparison engine         │
│ ├─ service.py      → Calculate overlap        │
│ └─ calculations    → Top 10, common holdings   │
│                                                 │
│ app/ingestion/     → Monthly data pipeline     │
│ ├─ top50.py        → Rank & match schemes     │
│ ├─ service.py      → Parse & validate         │
│ └─ cli.py          → Manual ingestion         │
│                                                 │
│ app/db/            → Database models          │
│ ├─ models.py       → SQLAlchemy ORM          │
│ └─ session.py      → Connection pool         │
│                                                 │
│ app/parsers/       → Portfolio parsing        │
│ ├─ universal_portfolio.py  → Multi-format    │
│ └─ base.py         → Common utilities        │
│                                                 │
│ app/downloaders/   → Official source fetch   │
│ ├─ generic.py      → Config-driven discovery  │
│ ├─ resolve.py      → Route to bespoke parsers│
│ └─ base.py         → Common download logic   │
│                                                 │
│ app/normalization/ → Data standardization    │
│ ├─ securities.py   → Company name matching   │
│ └─ industries.py   → Sector classification   │
│                                                 │
│ app/validation/    → Quality checks          │
│ ├─ classification.py → Classify fund type    │
│ ├─ portfolio.py    → Validate holdings       │
│ └─ reclassify.py   → Batch updates          │
│                                                 │
│ app/net.py         → TLS certificate handling│
│ └─ Avast interception workaround             │
└─────────────────────────────────────────────────┘
```

### Frontend (Next.js)

```
┌─────────────────────────────────────┐
│    Next.js Application              │
├─────────────────────────────────────┤
│ app/page.tsx        → Main page     │
│ app/layout.tsx      → Root layout   │
│                                     │
│ components/         → Reusable UI   │
│ ├─ FundSelector     → Dropdown      │
│ ├─ ComparisonTable  → Results       │
│ ├─ TopHoldings      → Holdings list │
│ └─ Charts           → Visualizations│
│                                     │
│ lib/                → Utilities     │
│ ├─ api.ts           → API client    │
│ └─ types.ts         → TypeScript    │
│                                     │
│ styles/             → CSS           │
│ ├─ globals.css      → Base styles   │
│ └─ components/      → Component CSS │
└─────────────────────────────────────┘
```

## Deployment Flow

```
Developer Push to GitHub
        │
        ▼
GitHub Actions Workflow (deploy.yml)
        │
        ├─────────────┬──────────────┐
        │             │              │
        ▼             ▼              ▼
   [Skipped]    Render Deploy   Vercel Deploy
                    │                │
        ┌───────────▼──────────┐    │
        │ Build Docker Image   │    │
        ├──────────────────────┤    │
        │ ✓ Copy Python files  │    │
        │ ✓ Install deps       │    │
        │ ✓ Test health check  │    │
        └───────────┬──────────┘    │
                    │               │
        ┌───────────▼──────────┐    │
        │ Deploy to Render     │    │
        ├──────────────────────┤    │
        │ ✓ Update container   │    │
        │ ✓ Run migrations     │    │
        │ ✓ Start service      │    │
        │ ✓ Check health       │    │
        └───────────┬──────────┘    │
                    │               │
                    │    ┌──────────▼──────────┐
                    │    │ Build Next.js App  │
                    │    ├───────────────────┤
                    │    │ ✓ Install deps    │
                    │    │ ✓ Build static    │
                    │    │ ✓ Generate routes │
                    │    └────────┬──────────┘
                    │             │
                    │    ┌────────▼────────┐
                    │    │Deploy to Vercel │
                    │    ├────────────────┤
                    │    │✓ CDN cache      │
                    │    │✓ SSL/TLS        │
                    │    │✓ Edge functions │
                    │    └────────┬────────┘
                    │             │
                    └─────┬───────┘
                          │
                    ✅ Live & Running
```

## Security Architecture

```
┌──────────────────────────────────────────┐
│        SECURITY LAYERS                   │
└──────────────────────────────────────────┘

1. TRANSPORT (HTTPS/TLS)
   ├─ Vercel: Auto SSL/TLS
   ├─ Render: Auto SSL/TLS
   └─ Database: Encrypted connection string

2. APPLICATION
   ├─ CORS: Restricted to frontend origin
   ├─ GET-only APIs (safe, cacheable)
   └─ Input validation (Pydantic schemas)

3. DATABASE
   ├─ Connection pooling (secure)
   ├─ SQL parameterization (injection-safe)
   ├─ Read-only for production data
   └─ Automated backups (Render)

4. SOURCE VERIFICATION
   ├─ Domain pinning (only official AMC hosts)
   ├─ SHA-256 verification of all files
   ├─ TLS certificate validation
   └─ Avast interception detection/workaround

5. INGESTION SAFETY
   ├─ Schema validation (Pydantic)
   ├─ Portfolio reconciliation
   ├─ Duplicate detection
   └─ Immutable monthly snapshots
```

## Performance Characteristics

```
Free Tier Constraints:
├─ Cold Start: ~30-60 sec (Render free tier)
├─ Response Time: <200ms (after warm)
├─ Database Queries: <100ms average
├─ Frontend Build: ~1-2 min (Vercel)
└─ Monthly Ingestion: ~5-10 min (depending on AMCs)

Optimization Strategies:
├─ Render: Add health check (keep service warm)
├─ Database: Indexed queries for fund lookup
├─ Frontend: Next.js static generation
├─ API: Cache available funds/dates
└─ Ingestion: Parallel downloads (when possible)
```

---

**See [`DEPLOYMENT.md`](./DEPLOYMENT.md) for setup instructions.**
