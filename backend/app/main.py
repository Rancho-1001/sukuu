import logging

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
    users,
    webhooks,
)
from app.core.config import settings
from app.services.audit import AuditMiddleware

# uvicorn configures its own loggers and leaves the root at WARNING, which
# would hide the "looks right" lines below - the ones that end a debugging
# session by saying there is nothing wrong here.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("sukuu.startup")

app = FastAPI(
    title="Sukuu API",
    description="School fee management - students, fee assignments, and payments.",
    version="0.1.0",
)

register_error_handlers(app)

app.add_middleware(AuditMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Said once at startup, so a misconfigured deploy explains itself in the logs
# instead of as a stream of "invalid signature" rejections. Shape only - the
# prefix and the length - never the value.
def _describe_secret(name: str, value: str, expected_prefix: str) -> None:
    if not value or value.endswith("placeholder"):
        logger.warning("%s is not set - its gateway will not work", name)
    elif not value.startswith(expected_prefix):
        logger.warning(
            "%s does not start with %r (length %d) - every delivery will be rejected",
            name,
            expected_prefix,
            len(value),
        )
    else:
        logger.info("%s looks right: %s… (length %d)", name, expected_prefix, len(value))


logger.info(
    "Payment gateway: %s, charging in %s", settings.payment_gateway.value, settings.currency.upper()
)
_describe_secret("STRIPE_WEBHOOK_SECRET", settings.stripe_webhook_secret, "whsec_")
_describe_secret("STRIPE_SECRET_KEY", settings.stripe_secret_key, "sk_")
_describe_secret("PAYSTACK_SECRET_KEY", settings.paystack_secret_key, "sk_")
logger.info("CORS origins: %s", settings.cors_origins)

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
app.include_router(users.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
