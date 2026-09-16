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
    """How the parent paid - what a bursar means by "method".

    Not which company processed it: that is :class:`PaymentProvider`. The two
    were one field when Stripe was the only processor and "stripe" meant
    "card". A Ghanaian parent paying by MTN MoMo through Paystack is a mobile
    money payment, and the ledger should say so.
    """

    CASH = "cash"
    CARD = "card"
    MOBILE_MONEY = "mobile_money"
    BANK = "bank"


class PaymentProvider(enum.StrEnum):
    """Who processed an online payment. NULL on the row for cash."""

    STRIPE = "stripe"
    PAYSTACK = "paystack"
