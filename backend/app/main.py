from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_error_handlers
from app.api.routes import auth
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


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
