"""FastAPI application entry point."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import leads, notes, history, export
from api.routes import auth, tasks, pipeline, expenses, invoices, bookkeeping, hcad, workflows, imports, quotes, appointments
from api.routes import connections, insights, ml


@asynccontextmanager
async def lifespan(app: FastAPI):
    from api.scheduler import scheduler, load_active_schedules, schedule_retraining
    scheduler.start()
    load_active_schedules()
    schedule_retraining()
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
app.include_router(leads.router,    prefix="/api", tags=["Leads"])
app.include_router(notes.router,    prefix="/api", tags=["Notes"])
app.include_router(history.router,  prefix="/api", tags=["History"])
app.include_router(export.router,   prefix="/api", tags=["Export"])
app.include_router(tasks.router,    prefix="/api", tags=["Tasks"])
app.include_router(pipeline.router,  prefix="/api", tags=["Pipeline"])
app.include_router(expenses.router,    prefix="/api", tags=["Expenses"])
app.include_router(invoices.router,    prefix="/api", tags=["Invoices"])
app.include_router(quotes.router,      prefix="/api", tags=["Quotes"])
app.include_router(bookkeeping.router, prefix="/api", tags=["Bookkeeping"])
app.include_router(hcad.router,        prefix="/api", tags=["HCAD"])
app.include_router(workflows.router,   prefix="/api", tags=["Workflows"])
app.include_router(imports.router,     prefix="/api", tags=["Import"])
app.include_router(appointments.router, prefix="/api", tags=["Appointments"])
app.include_router(connections.router, prefix="/api", tags=["Connections"])
app.include_router(insights.router,    prefix="/api", tags=["Insights"])
app.include_router(ml.router,          prefix="/api", tags=["ML"])


@app.get("/api/health")
def health():
    return {"status": "ok"}
