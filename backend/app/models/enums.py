"""Enumerations shared by the models.

Stored as native Postgres enum types. ``values_callable`` makes SQLAlchemy
persist the *values* ("admin") rather than the Python member names ("ADMIN"),
which keeps the database readable when you query it by hand.
"""

from __future__ import annotations

import enum


class UserRole(enum.StrEnum):
    ADMIN = "admin"
    STAFF = "staff"
    PARENT = "parent"


class StudentStatus(enum.StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class BillingPeriod(enum.StrEnum):
    TERM = "term"
    MONTHLY = "monthly"
    ONE_TIME = "one_time"


class PaymentMethod(enum.StrEnum):
    STRIPE = "stripe"
    CASH = "cash"
