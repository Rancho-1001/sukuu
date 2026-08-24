from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_error_handlers
from app.api.routes import (
    auth,
    balances,
    checkout,
    classes,
    fee_assignments,
    fee_types,
    me,
    payments,
    reports,
    students,
    webhooks,
)
from app.core.config import settings
from app.services.audit import AuditMiddleware

app = FastAPI(
    title="Sukuu API",
    description="School fee management - students, fee assignments, and payments.",
    version="0.1.0",
)

register_error_handlers(app)

app.add_middleware(AuditMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(classes.router)
app.include_router(fee_types.router)
app.include_router(students.router)
app.include_router(fee_assignments.router)
app.include_router(payments.router)
app.include_router(balances.router)
app.include_router(checkout.router)
app.include_router(webhooks.router)
app.include_router(me.router)
app.include_router(reports.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
