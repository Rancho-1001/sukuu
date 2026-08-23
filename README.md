# Sukuu — School Fee Management System

[![CI](https://github.com/Rancho-1001/sukuu/actions/workflows/ci.yml/badge.svg)](https://github.com/Rancho-1001/sukuu/actions/workflows/ci.yml)

> A school management platform that lets administrators track student fees (tuition, feeding, uniforms), lets parents pay online and in installments, and gives staff a clean view of who owes what.

**Sukuu** means "school" in Twi. This was built after teaching in Ghana, where fee and feeding-payment tracking was largely manual and error-prone — spreadsheets, paper receipt books, and a bursar reconciling by hand.

> **Status:** In development. See [docs/spec.md](docs/spec.md) for the full specification and [Roadmap](#roadmap) for what is deliberately out of scope.

---

## What this project is about

Three things, deliberately:

1. **Full-stack with real payments** — React frontend, FastAPI backend, Postgres, Stripe integration with webhook-driven reconciliation.
2. **Access control that is actually enforced** — three roles with real permission boundaries in backend middleware, JWT auth, and an audit log. Not UI-only guards.
3. **Financial correctness** — partial payments, installments, overpayment rejection under concurrency, and money stored as exact decimals rather than floats.

## Core loop

```
Admin sets up school (students, classes, fee types)
   → assigns fees to students
      → parents/staff see what's owed
         → payments recorded (online via Stripe, or cash by staff)
            → dashboard shows paid vs. outstanding
```

## Roles & permissions

| Capability | Admin | Staff/Bursar | Parent |
|---|:---:|:---:|:---:|
| Manage students & classes | ✅ | ❌ | ❌ |
| Define/edit fee structures | ✅ | ❌ | ❌ |
| Assign fees to students/classes | ✅ | ❌ | ❌ |
| Record offline (cash) payments | ✅ | ✅ | ❌ |
| View all payments & reports | ✅ | ✅ | ❌ |
| View own child's fees only | — | — | ✅ |
| Pay fees online (Stripe) | — | — | ✅ |
| View own payment history | — | — | ✅ |

Every boundary above is enforced server-side. The UI hides what a role cannot do; the API refuses it.

## Tech stack

| Layer | Choice |
|---|---|
| Backend | FastAPI (Python 3.14) |
| Database | PostgreSQL |
| ORM / migrations | SQLAlchemy + Alembic |
| Frontend | React + Vite |
| Auth | PyJWT + bcrypt, with role-based dependency guards |
| Payments | Stripe (test mode), webhook-driven |
| Deploy | Render/Railway (API + DB), Vercel (frontend) |

## Data model

Seven tables: `users`, `students`, `classes`, `fee_types`, `fee_assignments`, `payments`, `audit_log`.

The centre of the model is **`fee_assignments` has many `payments`** — that one-to-many is what makes installments possible.

```
outstanding = fee_assignment.amount − SUM(payments.amount_paid)
```

Two rules the implementation takes seriously:

- **Money is never a float.** Amounts are `NUMERIC(12,2)` in Postgres and `Decimal` in Python.
- **Overpayment is rejected under concurrency.** The balance check and the payment insert happen in one transaction with a row lock on the fee assignment, so two simultaneous payments cannot both pass the check.

## Project structure

```
sukuu/
├── backend/
│   ├── app/
│   │   ├── api/routes/    # HTTP endpoints, thin
│   │   ├── core/          # config, security, JWT, role guards
│   │   ├── db/            # session, base, migrations
│   │   ├── models/        # SQLAlchemy models
│   │   ├── schemas/       # Pydantic request/response models
│   │   └── services/      # business logic (balances, payments, audit)
│   └── tests/
│       ├── unit/          # pure logic, no I/O
│       ├── api/           # HTTP behaviour via TestClient
│       └── integration/   # real Postgres, marked `db`
├── frontend/              # React + Vite
└── docs/
    └── spec.md            # full project specification
```

## Getting started

Prerequisites: Python 3.14, Node 20+, PostgreSQL 16+.

If you don't have Python 3.14, [uv](https://docs.astral.sh/uv/) installs it without touching your system Python or needing admin rights:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh && uv python install 3.14
```

```bash
git clone https://github.com/Rancho-1001/sukuu.git
cd sukuu
```

**Backend**

```bash
cd backend
uv venv --python 3.14 && source .venv/bin/activate
uv pip install -r requirements-dev.txt
cp .env.example .env    # then fill in DATABASE_URL, JWT_SECRET, Stripe keys
uvicorn app.main:app --reload
```

API docs are then at `http://localhost:8000/docs`.

**Frontend**

```bash
cd frontend
npm install
npm run dev
```

## Testing

```bash
cd backend
pytest                       # everything
pytest tests/unit -q         # pure logic, no database needed
pytest -m db                 # only the tests that need Postgres
pytest --cov                 # with a coverage report
ruff check . && ruff format --check .
```

The suite is split three ways by what each layer needs:

- **`tests/unit/`** — the money rules in `app/services/balances.py`. No database, no HTTP, no fixtures. This is where partial payments, exact payoffs, rounding, and overpayment rejection are pinned down, because that logic is the part of the product most expensive to get wrong.
- **`tests/api/`** — endpoint behaviour through FastAPI's `TestClient`, including the role boundaries. A permission test that only checks the UI proves nothing; these hit the API directly.
- **`tests/integration/`** — anything needing real SQL, marked `db`. These **skip** when no Postgres is reachable so local runs stay useful, and CI runs a Postgres 16 service container so they cannot skip silently where it counts.

Two deliberate choices worth naming:

**No SQLite substitute.** Tests run against the same Postgres the app uses. Swapping in SQLite would break `NUMERIC` semantics and `SELECT ... FOR UPDATE` — precisely the two things the financial tests exist to verify.

**Tests for unwritten code skip themselves, then activate.** `tests/integration/test_payment_concurrency.py` guards on `importorskip("app.services.payments")`, so it stays quiet until that module exists and then starts running on its own. Nothing has to be un-skipped by hand and forgotten.

CI runs lint, format check, and the full suite against Python 3.14 and Postgres 16 on every push and pull request.

## Build order

1. **Week 1** — Schema, migrations, JWT auth, role guards, and audit logging. Security scaffolding goes in *before* the endpoints so nothing has to be retrofitted.
2. **Week 2** — Admin CRUD (students, classes, fee types, assignments) behind those guards, plus the outstanding-balance service and its tests.
3. **Week 3** — Parent payment flow, Stripe checkout, webhook reconciliation, installments, and the dashboard.

## Roadmap

Deliberately **not** in v1:

- Attendance tracking
- Grades / report cards
- Timetables & scheduling
- SMS / email fee reminders *(the most obvious next feature)*
- Multi-school / multi-tenant support
- Refunds & reversals
- Feeding as a prepaid top-up balance
- Localized payment gateways (Paystack / Flutterwave)

## Production notes

**Payment gateway.** Stripe does not operate in Ghana directly, so this demo uses Stripe USD test mode — the standard choice for a portfolio build. A production deployment for the target market would use **Paystack** or **Flutterwave**, both of which support mobile money, which is how most school fees actually get paid there.

**Currency.** The demo is USD. A production version would be locale-aware and denominated in GHS.

**Parent–student relationship.** v1 models one parent per student. Real households often have two guardians; that would become a join table in v2.

## License

MIT — see [LICENSE](LICENSE).
