"""SQLAlchemy models.

Imported here so that ``Base.metadata`` is fully populated by the time Alembic
autogenerate inspects it. A model that is never imported is a model Alembic
will happily generate a DROP TABLE for.
"""

from app.models.enums import BillingPeriod, PaymentMethod, StudentStatus, UserRole
from app.models.fees import AuditLog, FeeAssignment, FeeType, Payment
from app.models.school import SchoolClass, Student, User

__all__ = [
    "AuditLog",
    "BillingPeriod",
    "FeeAssignment",
    "FeeType",
    "Payment",
    "PaymentMethod",
    "SchoolClass",
    "Student",
    "StudentStatus",
    "User",
    "UserRole",
]
