# Axon CRM

A full-stack business intelligence and CRM platform built for small service businesses. Axon pulls property data from public sources, scores leads using configurable signals, and surfaces the highest-opportunity prospects in a mobile-first dashboard — alongside task management, a Kanban pipeline, expense tracking, and invoicing with accounts receivable reporting.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Environment Variables](#environment-variables)
  - [Database Setup](#database-setup)
  - [Running Locally](#running-locally)
- [Data Pipeline](#data-pipeline)
  - [How the Pipeline Works](#how-the-pipeline-works)
  - [Lead Scoring Engine](#lead-scoring-engine)
  - [Running the Pipeline](#running-the-pipeline)
  - [Scheduled Pipeline Runs](#scheduled-pipeline-runs)
- [API Reference](#api-reference)
- [Frontend Pages](#frontend-pages)
- [Deployment](#deployment)
  - [Frontend — Vercel](#frontend--vercel)
  - [Backend — Railway / Render / Fly.io](#backend--railway--render--flyio)
- [Database Migrations](#database-migrations)
- [Authentication](#authentication)

---

## Overview

Axon is designed for contractors, service companies, and small businesses that do outbound prospecting. Instead of cold-calling random lists, the pipeline identifies homeowners who are statistically most likely to need your service — based on home age, equity, recent sale activity, garage size, zip income data, and permit history — then scores and ranks them so your team works the hottest leads first.

The platform is self-hosted and data-sovereign: all leads, notes, tasks, invoices, and expenses live in your own PostgreSQL database.

---

## Features

### Home Dashboard
- At-a-glance business health screen shown immediately after login
- Personalized greeting with time-of-day awareness
- Pipeline value card (sum of all estimated job values in active stages)
- KPI grid: active leads, tasks due today, revenue collected YTD
- "Needs Attention" alerts for overdue tasks and outstanding invoices
- Quick-action buttons: New Lead, Create Invoice, Log Expense, View Pipeline
- Recent top-scored leads strip with one-tap navigation
- Mobile-first, responsive 2→4 column layout

### Lead Management
- Scored lead table with sort, filter by zip/grade/vertical/status
- Lead detail drawer: property info, owner details, estimated job value
- Inline status updates (New → Contacted → Qualified → Quote Sent → Won/Lost)
- Notes and activity history per lead
- CSV export with current filters applied

### Kanban Pipeline
- Visual drag-free stage board grouped by lead status
- Stage summary: count and total job value per column
- Filter by vertical and zip code
- Cards show score grade, address, owner name, estimated value

### Task Management
- Tasks linked optionally to specific leads/properties
- Due date, priority (low / normal / high / urgent), assignment
- Overdue and due-today counts surfaced in the home dashboard
- Task bell notification indicator in every page header

### Expense Tracker
- Log business expenses by category (fuel, materials, meals, tools, advertising, subcontractor, office, other)
- Tax deductible flag per expense
- Monthly summary by category
- Link expenses to specific properties/jobs
- CSV export

### Invoicing & Accounts Receivable
- Full invoice lifecycle: Draft → Sent → Partial → Paid / Overdue / Void
- Line item support with quantity × unit price
- Tax rate per invoice
- Payment recording with payment method tracking
- AR summary: total invoiced, collected, outstanding, overdue
- Aging report buckets
- CSV export

### Bookkeeping
- P&L report by month for any year (revenue vs. expenses vs. net profit)
- Job costing table: revenue, expenses, profit margin per property

### Pipeline Scheduler
- Schedule pipeline runs by zip code, vertical, day of week, and hour
- Active/inactive toggle per schedule
- Run history with status tracking (queued / running / done / failed)
- Background execution via APScheduler

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS v4 |
| Icons | lucide-react |
| Backend | FastAPI (Python 3.11+), Uvicorn |
| Database | PostgreSQL (primary), DuckDB (HCAD permit data) |
| Auth | JWT (python-jose), bcrypt password hashing |
| Scheduler | APScheduler 3.x |
| Data Pipeline | RentCast API, ATTOM API, Google Geocoding API, US Census ACS API |
| ORM | Raw SQL via psycopg2 |

---

## Project Structure

```
axon-crm/
├── api/                        # FastAPI application
│   ├── main.py                 # App entry point, CORS, router registration
│   ├── deps.py                 # Shared FastAPI dependencies (DB conn, current user)
│   ├── models.py               # Pydantic request/response models
│   ├── security.py             # JWT creation/verification, password hashing
│   ├── scheduler.py            # APScheduler setup and schedule loader
│   └── routes/
│       ├── auth.py             # POST /auth/login, GET /auth/me
│       ├── leads.py            # CRUD + status + job value endpoints
│       ├── notes.py            # Lead notes
│       ├── history.py          # Lead activity history
│       ├── export.py           # CSV export
│       ├── tasks.py            # Task CRUD + complete + counts
│       ├── pipeline.py         # Kanban groups, stats, schedules, run trigger
│       ├── expenses.py         # Expense CRUD + summary + export
│       ├── invoices.py         # Invoice CRUD + payments + AR summary + aging
│       └── bookkeeping.py      # P&L report, job costing
│
├── pipeline/                   # Data acquisition pipeline (run independently)
│   ├── seed.py                 # Step 1: Seed addresses from RentCast
│   ├── census.py               # Step 2: Enrich zip median income from Census ACS
│   ├── geocode.py              # Step 3: Geocode addresses via Google Maps
│   ├── property.py             # Step 4: Enrich property data from ATTOM
│   ├── permits.py              # Step 5: Pull permit counts from HCAD DuckDB
│   ├── score.py                # Step 6: Score and grade each lead
│   ├── hcad_enrichment.py      # Harris County Appraisal District enrichment
│   ├── hcad_store.py           # DuckDB interface for HCAD permit data
│   └── db.py                   # Pipeline DB helpers
│
├── db/
│   ├── migrate.py              # Migration runner CLI
│   └── migrations/
│       ├── 0001_auth.sql       # users table
│       ├── 0002_tasks.sql      # tasks table
│       ├── 0003_pipeline_stages.sql
│       ├── 0004_pipeline_jobs.sql
│       ├── 005_expenses.sql
│       └── 006_invoices.sql
│
├── frontend/                   # Next.js application
│   ├── app/
│   │   ├── layout.tsx          # Root layout (fonts, metadata)
│   │   ├── page.tsx            # Public landing page
│   │   ├── home/               # Home dashboard (post-login landing)
│   │   ├── dashboard/          # Lead management table
│   │   ├── pipeline/           # Kanban board
│   │   ├── tasks/              # Task list
│   │   ├── expenses/           # Expense tracker
│   │   ├── bookkeeping/        # Invoices + P&L
│   │   ├── settings/           # Pipeline schedule management
│   │   └── login/              # Authentication page
│   ├── components/
│   │   ├── HomeDashboard.tsx   # Home dashboard (KPIs, actions, alerts)
│   │   ├── Dashboard.tsx       # Lead table + filters + drawer
│   │   ├── AuthGuard.tsx       # Client-side route protection
│   │   ├── LeadTable.tsx       # Sortable, paginated lead table
│   │   ├── ContactDrawer.tsx   # Lead detail slide-out panel
│   │   ├── ScoreBadge.tsx      # A/B/C/D grade pill with score
│   │   ├── StatusSelect.tsx    # Inline status dropdown
│   │   ├── TaskBell.tsx        # Notification bell with overdue count
│   │   ├── TaskList.tsx        # Task list view
│   │   ├── TaskForm.tsx        # Create/edit task form
│   │   ├── ExpenseTracker.tsx  # Expense dashboard
│   │   ├── ExpenseForm.tsx     # Add/edit expense form
│   │   ├── ExpenseSummaryBar.tsx
│   │   ├── InvoiceList.tsx     # Invoice table
│   │   ├── InvoiceForm.tsx     # Create/edit invoice with line items
│   │   ├── InvoiceDetail.tsx   # Invoice detail + payment recording
│   │   ├── ARDashboard.tsx     # Accounts receivable overview
│   │   ├── BookkeepingDashboard.tsx
│   │   ├── BookkeepingOverview.tsx
│   │   ├── PnLChart.tsx        # Monthly P&L bar chart
│   │   ├── JobCostingTable.tsx
│   │   └── KanbanCard.tsx      # Pipeline board card
│   ├── lib/
│   │   ├── api.ts              # All API client functions
│   │   ├── auth.ts             # Token storage (localStorage)
│   │   └── types.ts            # TypeScript interfaces
│   └── middleware.ts           # Root redirect (/ → /home)
│
├── config.py                   # Scoring weights, API keys, thresholds
├── run_pipeline.py             # Pipeline CLI entry point
├── requirements.txt            # Python dependencies
└── .env                        # Environment variables (not committed)
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL 14+ (running locally or via a cloud provider)
- A virtual environment tool (`python -m venv` or `uv`)

### Environment Variables

Create a `.env` file in the project root:

```env
# Required
DATABASE_URL=postgresql://localhost/axon_crm
JWT_SECRET_KEY=your-long-random-secret-key-here

# Required for pipeline data enrichment
RENTCAST_API_KEY=your_key
ATTOM_API_KEY=your_key
GOOGLE_GEOCODE_KEY=your_key

# Optional (increases Census API rate limits)
CENSUS_API_KEY=your_key

# Optional (Harris County permit DuckDB path)
PERMIT_DB_PATH=/path/to/harris_county.duckdb

# Payments (Stripe Connect) — required to accept online invoice payments
STRIPE_SECRET_KEY=sk_test_...           # platform account secret key
STRIPE_WEBHOOK_SECRET=whsec_...         # from `stripe listen` or the dashboard
STRIPE_PLATFORM_FEE_PCT=0.02            # Axon's platform fee (2% default)

# Invoice delivery (optional per channel)
RESEND_API_KEY=re_...                   # email via Resend
RESEND_FROM_EMAIL=invoices@yourdomain.com
TWILIO_ACCOUNT_SID=AC...                # SMS via Twilio
TWILIO_AUTH_TOKEN=...
TWILIO_FROM_NUMBER=+15555550123

# Public base URL used to build customer pay links (/pay/<token>)
PUBLIC_APP_URL=http://localhost:3000
```

For the frontend, create `frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
# Base URL used to render copyable pay links in the invoice UI
NEXT_PUBLIC_APP_URL=http://localhost:3000
```

### Database Setup

1. Create the database:
```bash
createdb axon_crm
```

2. Run all migrations:
```bash
python db/migrate.py
```

3. Check migration status anytime:
```bash
python db/migrate.py status
```

4. Create a new migration file:
```bash
python db/migrate.py create add_customers
```

5. Create your first admin user (run once, then remove):
```bash
python -c "
from api.security import hash_password
import psycopg2, os
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
cur.execute(
  \"INSERT INTO users (username, email, password_hash, role) VALUES (%s, %s, %s, %s)\",
  ('admin', 'you@example.com', hash_password('your-password'), 'admin')
)
conn.commit()
conn.close()
print('User created.')
"
```

### Running Locally

**Backend:**
```bash
# Install dependencies
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start the API server
uvicorn api.main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
# Runs at http://localhost:3000
```

Navigate to `http://localhost:3000/login` and sign in. You'll be taken to the home dashboard.

---

## Data Pipeline

### How the Pipeline Works

The pipeline runs in 6 sequential steps for a given ZIP code and optional service vertical:

| Step | Module | Description |
|---|---|---|
| 1 | `pipeline/seed.py` | Pulls property records from RentCast API for the target ZIP |
| 2 | `pipeline/census.py` | Enriches each ZIP with median household income from US Census ACS |
| 3 | `pipeline/geocode.py` | Geocodes addresses to lat/lng using Google Maps Geocoding API |
| 4 | `pipeline/property.py` | Pulls home details (year built, sq ft, garage spaces, equity) from ATTOM |
| 5 | `pipeline/permits.py` | Queries HCAD DuckDB for 24-month permit activity per address |
| 6 | `pipeline/score.py` | Scores each property 0–100 and assigns a letter grade (A/B/C/D) |

### Lead Scoring Engine

Each lead receives a composite score (0–100) from six weighted signals:

| Signal | Default Weight | What it Measures |
|---|---|---|
| Home age | 25% | Age in renovation sweet spot (15–30 years) |
| Sale recency | 22% | Last sale within 24 months |
| Equity | 18% | Estimated equity ≥ $100,000 |
| Garage | 15% | Garage spaces ≥ 2 |
| Zip income | 12% | Zip median household income ≥ $75,000 |
| Permit activity | 8% | ≥ 2 permits pulled in last 24 months |

**Grade bands:**

| Score | Grade |
|---|---|
| 75–100 | A |
| 55–74 | B |
| 35–54 | C |
| 0–34 | D |

**Per-vertical weight overrides** are configurable in `config.py`. For example, epoxy flooring weights garage spaces more heavily; solar weights equity and income higher. Adding a new vertical requires only adding a key to `VERTICAL_WEIGHTS`.

### Running the Pipeline

```bash
# Single ZIP code
python run_pipeline.py --zip 77002

# ZIP + service vertical
python run_pipeline.py --zip 77002 --vertical epoxy_flooring

# Multiple ZIPs from a file (one per line)
python run_pipeline.py --zip-file zips.txt --vertical roofing

# Seed from a local CSV instead of RentCast
python run_pipeline.py --zip 77002 --seed-csv /path/to/addresses.csv

# Skip specific steps (comma-separated)
python run_pipeline.py --zip 77002 --skip geocode,permits

# Limit number of records processed
python run_pipeline.py --zip 77002 --limit 100
```

Available verticals (defined in `config.py`): `epoxy_flooring`, `pool_maintenance`, `solar` — or pass any custom string.

### Scheduled Pipeline Runs

Pipeline runs can be scheduled from the **Settings** page in the app UI. Each schedule specifies:
- ZIP code
- Vertical (optional)
- Day of week
- Hour of day

The APScheduler background process (started with the API server) picks up active schedules on boot and runs them automatically. Run history is tracked in the `pipeline_jobs` table.

---

## API Reference

The FastAPI server exposes interactive docs at `http://localhost:8000/docs` (Swagger UI) and `http://localhost:8000/redoc`.

All protected endpoints require `Authorization: Bearer <token>` in the request header.

### Auth
| Method | Path | Description |
|---|---|---|
| POST | `/api/auth/login` | Authenticate and receive JWT access token |
| GET | `/api/auth/me` | Get current user info |

### Leads
| Method | Path | Description |
|---|---|---|
| GET | `/api/leads` | List leads with filtering, sorting, pagination |
| GET | `/api/leads/{id}` | Get single lead |
| PATCH | `/api/leads/{id}/status` | Update lead status |
| PATCH | `/api/leads/{id}/job-value` | Update estimated job value |

### Notes & History
| Method | Path | Description |
|---|---|---|
| GET | `/api/leads/{id}/notes` | Get notes for a lead |
| POST | `/api/leads/{id}/notes` | Add a note |
| GET | `/api/leads/{id}/history` | Get activity history |
| POST | `/api/leads/{id}/history` | Log an activity |

### Export
| Method | Path | Description |
|---|---|---|
| GET | `/api/export` | Download leads as CSV (respects current filters) |

### Tasks
| Method | Path | Description |
|---|---|---|
| GET | `/api/tasks` | List tasks (filter by due, overdue, property, complete) |
| GET | `/api/tasks/counts` | Get due-today and overdue counts |
| GET | `/api/leads/{id}/tasks` | Tasks linked to a lead |
| POST | `/api/tasks` | Create task |
| POST | `/api/tasks/{id}/complete` | Mark task complete |
| DELETE | `/api/tasks/{id}` | Delete task |

### Pipeline
| Method | Path | Description |
|---|---|---|
| GET | `/api/pipeline` | Leads grouped by status (Kanban) |
| GET | `/api/pipeline/stats` | Count and total value per stage |
| GET | `/api/pipeline-schedules` | List pipeline schedules |
| POST | `/api/pipeline-schedules` | Create schedule |
| PATCH | `/api/pipeline-schedules/{id}` | Update schedule |
| DELETE | `/api/pipeline-schedules/{id}` | Delete schedule |
| POST | `/api/pipeline/run` | Trigger an ad-hoc pipeline run |
| GET | `/api/pipeline/runs` | Run history |

### Expenses
| Method | Path | Description |
|---|---|---|
| GET | `/api/expenses` | List expenses with filters |
| GET | `/api/expenses/summary` | Totals by category for a given month/year |
| POST | `/api/expenses` | Create expense |
| PATCH | `/api/expenses/{id}` | Update expense |
| DELETE | `/api/expenses/{id}` | Delete expense |
| GET | `/api/expenses/export` | Download expenses as CSV |

### Invoices & AR
| Method | Path | Description |
|---|---|---|
| GET | `/api/invoices` | List invoices |
| GET | `/api/invoices/{id}` | Get invoice with line items and payments |
| POST | `/api/invoices` | Create invoice |
| PATCH | `/api/invoices/{id}` | Update invoice |
| DELETE | `/api/invoices/{id}` | Delete invoice |
| POST | `/api/invoices/{id}/payments` | Record a payment |
| DELETE | `/api/invoices/{id}/payments/{pid}` | Delete a payment |
| GET | `/api/invoices/summary` | AR summary (invoiced, collected, outstanding, overdue) |
| GET | `/api/invoices/aging` | Aging report buckets |
| GET | `/api/invoices/export` | Download invoices as CSV |

### Bookkeeping
| Method | Path | Description |
|---|---|---|
| GET | `/api/bookkeeping/pnl` | Monthly P&L report for a given year |
| GET | `/api/bookkeeping/job-costing` | Revenue, expenses, and margin per property |

### Utility
| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Server health check |
| GET | `/api/zips` | List all ZIP codes in the database |

---

## Frontend Pages

| Route | Page | Auth Required |
|---|---|---|
| `/` | Public landing / marketing page | No |
| `/login` | Sign in | No |
| `/home` | Home dashboard (post-login landing) | Yes |
| `/dashboard` | Lead management table | Yes |
| `/pipeline` | Kanban board | Yes |
| `/tasks` | Task list | Yes |
| `/expenses` | Expense tracker | Yes |
| `/bookkeeping` | Invoices + P&L + AR | Yes |
| `/settings` | Pipeline schedule management | Yes |

Authentication is handled client-side: the JWT token is stored in `localStorage` under the key `axon_token`. Protected pages are wrapped in `<AuthGuard>` which redirects to `/login` if no token is present. A 401 response from any API call also clears the token and redirects.

---

## Deployment

### Frontend — Vercel

1. Push the repo to GitHub
2. Import the repo at [vercel.com/new](https://vercel.com/new)
3. Set **Root Directory** to `frontend`
4. Vercel auto-detects Next.js — no build command changes needed
5. Add environment variable:
   ```
   NEXT_PUBLIC_API_URL=https://your-api-domain.com
   ```
6. Deploy — every push to `master` triggers a new deployment

### Backend — Railway / Render / Fly.io

The FastAPI backend requires a persistent server with access to PostgreSQL. Recommended options:

**Railway** (easiest):
1. Create a new project and connect your GitHub repo
2. Add a PostgreSQL service — Railway provides `DATABASE_URL` automatically
3. Set the start command: `uvicorn api.main:app --host 0.0.0.0 --port $PORT`
4. Add remaining environment variables (JWT secret, API keys)
5. Run migrations after deploy: `python db/migrate.py`

**Render**:
1. Create a new Web Service from your GitHub repo
2. Build command: `pip install -r requirements.txt`
3. Start command: `uvicorn api.main:app --host 0.0.0.0 --port $PORT`
4. Add a PostgreSQL database and link the `DATABASE_URL`

**After deploying the backend**, update your Vercel frontend environment variable `NEXT_PUBLIC_API_URL` to the backend's public URL, and add the frontend domain to the `allow_origins` list in `api/main.py`.

---

## Database Migrations

Migrations live in `db/migrations/` as numbered `.sql` files. The runner tracks applied migrations in a `schema_migrations` table.

```bash
# Run all pending migrations
python db/migrate.py

# Check what's been applied
python db/migrate.py status

# Scaffold a new migration file
python db/migrate.py create add_customers
```

Migrations run in filename order. Always test on a development database before applying to production.

---

## Authentication

- Passwords are hashed with bcrypt via `passlib`
- JWTs are signed with HS256 using `JWT_SECRET_KEY` from the environment
- Tokens expire after 8 hours
- The secret key defaults to a placeholder string — **always set a real secret in production**

To rotate credentials, update `JWT_SECRET_KEY` in your environment. All existing tokens will be immediately invalidated.
