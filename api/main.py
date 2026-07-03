"""FastAPI application entry point."""
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.entitlements import require_module
from api.routes import leads, notes, history, export, record_fields, segments, messaging
from api.routes import auth, tasks, pipeline, expenses, invoices, bookkeeping, hcad, workflows, imports, quotes
from api.routes import policies, orders, appointments, objects, order_imports
from api.routes import connections, insights, ml, oauth, map as map_routes
from api.routes import stripe_payments, twilio_inbound

log = logging.getLogger(__name__)


def _check_hcad_source() -> None:
    """Warn loudly (non-fatal) if HCAD seeding is selected but no data is loaded.

    On Render the DuckDB file is ephemeral, so the durable Postgres mirror must be
    populated (see docs/RENDER_DEPLOYMENT.md). Without this check a misconfigured
    deploy would silently seed 0 rows on every run.
    """
    from config import SEED_SOURCE
    if SEED_SOURCE != "hcad":
        return
    from pipeline import hcad_store
    if not hcad_store.hcad_available():
        log.warning(
            "SEED_SOURCE=hcad but no HCAD data is available (no DuckDB file at "
            "PERMIT_DB_PATH and hcad_properties is empty). Seeding will return 0 "
            "rows. Load the Postgres mirror with tools/load_hcad_to_postgres.py — "
            "see docs/RENDER_DEPLOYMENT.md."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    from api.scheduler import (
        scheduler, load_active_schedules, schedule_retraining,
        schedule_workflow_tick, schedule_account_rescore, schedule_recurring_invoices,
    )
    scheduler.start()
    load_active_schedules()
    schedule_retraining()
    schedule_workflow_tick()
    schedule_account_rescore()
    schedule_recurring_invoices()
    _check_hcad_source()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(
    title="Axon CRM API",
    description="Local service business lead scoring and contact management",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", "http://127.0.0.1:3000",
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:5174", "http://127.0.0.1:5174",
        "https://axon-crm-sigma.vercel.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,     prefix="/api", tags=["Auth"])
app.include_router(oauth.router,    prefix="/api", tags=["Auth"])
app.include_router(leads.router,    prefix="/api", tags=["Leads"])
# Custom record fields are part of the core record model — always available.
app.include_router(record_fields.router, prefix="/api", tags=["RecordFields"])
# Saved segments are core list-view conveniences — always available.
app.include_router(segments.router, prefix="/api", tags=["Segments"])
# Contact-level messaging (templates + per-record send) — core.
app.include_router(messaging.router, prefix="/api", tags=["Messaging"])
app.include_router(notes.router,    prefix="/api", tags=["Notes"])
app.include_router(history.router,  prefix="/api", tags=["History"])
app.include_router(export.router,   prefix="/api", tags=["Export"])
# Tasks and the core pipeline (Kanban board view + stages) are part of `core` and
# are always available. The data-acquisition/refresh endpoints inside pipeline.py
# are gated per-endpoint on the `prospecting` module (see api/routes/pipeline.py).
app.include_router(tasks.router,    prefix="/api", tags=["Tasks"])
app.include_router(pipeline.router,  prefix="/api", tags=["Pipeline"])
# Single-concern feature routers are gated as whole modules here. Mixed-concern
# routers (pipeline.py) gate per-endpoint instead. connections.py stays ungated:
# it is generic integration infra (Meta + Stripe OAuth); only the marketing
# *analytics* (insights.py) is gated on the `marketing` module.
app.include_router(expenses.router,    prefix="/api", tags=["Expenses"],
                   dependencies=[Depends(require_module("bookkeeping"))])
app.include_router(invoices.router,    prefix="/api", tags=["Invoices"],
                   dependencies=[Depends(require_module("invoicing"))])
app.include_router(quotes.router,      prefix="/api", tags=["Quotes"],
                   dependencies=[Depends(require_module("quotes"))])
# Public, token-addressed customer-facing links stay ungated: they must work
# without the seller's login or plan, and gating them re-introduces a `token`
# path/query param collision with `get_current_user` (see api/routes/invoices.py
# and api/routes/quotes.py).
app.include_router(invoices.public_router, prefix="/api", tags=["Invoices"])
app.include_router(quotes.public_router,   prefix="/api", tags=["Quotes"])
# Online payments (Stripe Connect Express) ride the invoicing module; the
# public router (pay page, checkout, webhook) stays ungated for the same
# reasons as above — customers and Stripe's webhook deliveries have no login.
app.include_router(stripe_payments.router, prefix="/api", tags=["Payments"],
                   dependencies=[Depends(require_module("invoicing"))])
app.include_router(stripe_payments.public_router, prefix="/api", tags=["Payments"])
# Inbound Twilio SMS (two-way messaging) — Twilio calls it, signature-verified.
app.include_router(twilio_inbound.public_router, prefix="/api", tags=["Messaging"])
app.include_router(bookkeeping.router, prefix="/api", tags=["Bookkeeping"],
                   dependencies=[Depends(require_module("bookkeeping"))])
# Associated child objects (Phase 5) — each gated as a whole module. Presets
# opt verticals in (insurance → policies, retail → orders, …); existing
# accounts were backfilled OFF in migration 043.
app.include_router(policies.router,     prefix="/api", tags=["Policies"],
                   dependencies=[Depends(require_module("policies"))])
app.include_router(orders.router,       prefix="/api", tags=["Orders"],
                   dependencies=[Depends(require_module("orders"))])
app.include_router(order_imports.router, prefix="/api", tags=["Orders"],
                   dependencies=[Depends(require_module("orders"))])
app.include_router(appointments.router, prefix="/api", tags=["Appointments"],
                   dependencies=[Depends(require_module("appointments"))])
# Ungated: internally checks account_has_module per aggregate block.
app.include_router(objects.router,      prefix="/api", tags=["Objects"])
app.include_router(hcad.router,        prefix="/api", tags=["HCAD"],
                   dependencies=[Depends(require_module("prospecting"))])
app.include_router(workflows.router,   prefix="/api", tags=["Workflows"],
                   dependencies=[Depends(require_module("automation"))])
app.include_router(imports.router,     prefix="/api", tags=["Import"],
                   dependencies=[Depends(require_module("prospecting"))])
app.include_router(connections.router, prefix="/api", tags=["Connections"])
app.include_router(insights.router,    prefix="/api", tags=["Insights"],
                   dependencies=[Depends(require_module("marketing"))])
app.include_router(ml.router,          prefix="/api", tags=["ML"],
                   dependencies=[Depends(require_module("prospecting"))])
app.include_router(map_routes.router,  prefix="/api", tags=["Map"],
                   dependencies=[Depends(require_module("map"))])


@app.get("/api/health")
def health():
    return {"status": "ok"}
