"""Development seed data.

Deliberately uneven: some fees settled, some part-paid through several
installments, some untouched, and a couple of students carrying arrears from
an earlier term. A demo where every student owes the same round number reads
as fixture data at a glance, which undercuts the thing the demo is for.

Run with:  python -m app.db.seed
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal

import bcrypt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import (
    BillingPeriod,
    FeeAssignment,
    FeeType,
    Payment,
    PaymentMethod,
    SchoolClass,
    Student,
    StudentStatus,
    User,
    UserRole,
)

# Fixed so the demo looks identical on every machine and in screenshots.
SEED = 20260824
DEMO_PASSWORD = "sukuu-demo"

FIRST_NAMES = [
    "Ama",
    "Kwame",
    "Akosua",
    "Yaw",
    "Abena",
    "Kofi",
    "Adwoa",
    "Kwabena",
    "Afua",
    "Kwaku",
    "Akua",
    "Yaa",
    "Kojo",
    "Esi",
    "Fiifi",
    "Nana",
    "Serwaa",
    "Kwesi",
    "Maame",
    "Kobby",
    "Efua",
    "Kwadwo",
    "Adjoa",
    "Sena",
    "Delali",
    "Selorm",
    "Mawuli",
    "Elikem",
]
LAST_NAMES = [
    "Mensah",
    "Osei",
    "Boateng",
    "Asante",
    "Owusu",
    "Addo",
    "Danso",
    "Appiah",
    "Baidoo",
    "Quaye",
    "Nyarko",
    "Amoah",
    "Tetteh",
    "Agyeman",
    "Darko",
]


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode()[:72], bcrypt.gensalt()).decode()


def already_seeded(session: Session) -> bool:
    return session.scalar(select(Student.id).limit(1)) is not None


def seed(session: Session) -> None:
    rng = random.Random(SEED)

    admin = User(
        email="admin@sukuu.demo",
        password_hash=hash_password(DEMO_PASSWORD),
        name="Grace Adjei",
        role=UserRole.ADMIN,
    )
    bursar = User(
        email="bursar@sukuu.demo",
        password_hash=hash_password(DEMO_PASSWORD),
        name="Samuel Ofori",
        role=UserRole.STAFF,
    )
    session.add_all([admin, bursar])
    session.flush()

    classes = [
        SchoolClass(name=name, academic_year="2026")
        for name in ("Grade 4A", "Grade 4B", "Grade 5A", "Grade 5B")
    ]
    session.add_all(classes)

    tuition = FeeType(
        name="Tuition",
        description="Termly tuition",
        default_amount=Decimal("450.00"),
        billing_period=BillingPeriod.TERM,
    )
    feeding = FeeType(
        name="Feeding",
        description="School lunch programme",
        default_amount=Decimal("120.00"),
        billing_period=BillingPeriod.MONTHLY,
    )
    uniform = FeeType(
        name="Uniform",
        description="Two sets, issued at intake",
        default_amount=Decimal("85.00"),
        billing_period=BillingPeriod.ONE_TIME,
    )
    session.add_all([tuition, feeding, uniform])
    session.flush()

    # One parent account is a real login for the demo; the rest are filler so
    # the class lists look populated.
    demo_parent = User(
        email="parent@sukuu.demo",
        password_hash=hash_password(DEMO_PASSWORD),
        name="Abena Owusu",
        role=UserRole.PARENT,
    )
    session.add(demo_parent)
    session.flush()

    students: list[Student] = []
    for i in range(26):
        first = FIRST_NAMES[i % len(FIRST_NAMES)]
        last = LAST_NAMES[(i * 7) % len(LAST_NAMES)]
        parent = demo_parent if i < 2 else None
        if parent is None:
            parent = User(
                email=f"parent{i:02d}@sukuu.demo",
                password_hash=hash_password(DEMO_PASSWORD),
                name=f"{rng.choice(FIRST_NAMES)} {last}",
                role=UserRole.PARENT,
            )
            session.add(parent)
            session.flush()

        student = Student(
            first_name=first,
            last_name=last,
            admission_number=f"SKU-2026-{i + 1:03d}",
            status=StudentStatus.ACTIVE if i < 25 else StudentStatus.INACTIVE,
            school_class=classes[i % len(classes)],
            parent=parent,
        )
        session.add(student)
        students.append(student)
    session.flush()

    today = date.today()
    assignments: list[FeeAssignment] = []
    for student in students:
        assignments.append(
            FeeAssignment(
                student=student,
                fee_type=tuition,
                amount=tuition.default_amount,
                due_date=today + timedelta(days=30),
                period_label="Term 1 2026",
            )
        )
        assignments.append(
            FeeAssignment(
                student=student,
                fee_type=feeding,
                amount=feeding.default_amount,
                due_date=today + timedelta(days=14),
                period_label="Aug 2026",
            )
        )
        # Only some students were issued a uniform this intake.
        if rng.random() < 0.4:
            assignments.append(
                FeeAssignment(
                    student=student,
                    fee_type=uniform,
                    amount=uniform.default_amount,
                    due_date=today - timedelta(days=20),
                    period_label="Intake 2026",
                )
            )
    session.add_all(assignments)
    session.flush()

    # Spread of payment states: fully settled, part paid in installments,
    # a token payment, and nothing at all.
    for assignment in assignments:
        roll = rng.random()
        if roll < 0.30:
            installments = [assignment.amount]
        elif roll < 0.60:
            half = (assignment.amount / 2).quantize(Decimal("0.01"))
            installments = [half, assignment.amount - half]
        elif roll < 0.75:
            part = (assignment.amount / 3).quantize(Decimal("0.01"))
            installments = [part]
        elif roll < 0.85:
            installments = [Decimal("20.00")]
        else:
            installments = []

        for n, amount in enumerate(installments):
            if amount <= 0:
                continue
            cash = rng.random() < 0.45
            session.add(
                Payment(
                    fee_assignment=assignment,
                    amount_paid=amount,
                    method=PaymentMethod.CASH if cash else PaymentMethod.STRIPE,
                    stripe_payment_intent_id=None if cash else f"pi_seed_{assignment.id}_{n}",
                    stripe_event_id=None if cash else f"evt_seed_{assignment.id}_{n}",
                    recorded_by=bursar if cash else None,
                )
            )

    session.commit()


def main() -> None:
    with SessionLocal() as session:
        if already_seeded(session):
            print("Database already has students; refusing to seed on top of them.")
            print("Reset with: alembic downgrade base && alembic upgrade head")
            return
        seed(session)
        print("Seeded.")
        print(f"  admin   admin@sukuu.demo   / {DEMO_PASSWORD}")
        print(f"  bursar  bursar@sukuu.demo  / {DEMO_PASSWORD}")
        print(f"  parent  parent@sukuu.demo  / {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
