"""FastAPI application entry point."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import leads, notes, history, export

app = FastAPI(
    title="Smart CRM API",
    description="Local service business lead scoring and contact management",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:5174", "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(leads.router,   prefix="/api", tags=["Leads"])
app.include_router(notes.router,   prefix="/api", tags=["Notes"])
app.include_router(history.router, prefix="/api", tags=["History"])
app.include_router(export.router,  prefix="/api", tags=["Export"])


@app.get("/api/health")
def health():
    return {"status": "ok"}
