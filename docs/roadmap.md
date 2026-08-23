# Build roadmap

Every task between the current repository and a deployed, demo-ready project.

Phases are numbered because they are a dependency chain, not a preference: the payment
work cannot start before the models exist, and the models should not be written before
the role guards do.

**Phase 0 is closed.** Postgres 16 is running locally and the `db`-marked tests execute
rather than skip, so Phase 1 onward can be written and tested. Stripe account setup moved
to Phase 5, which is where the first line of code that reads a Stripe key gets written.

---

## Phase 0 — Environment and accounts

- [x] Git repository created and pushed to GitHub
- [x] README, LICENSE, .gitignore, spec moved to `docs/`
- [x] Python 3.14.7 installed via uv (OpenSSL 3.5.7; system Python untouched)
- [x] Dependencies pinned and installing cleanly
- [x] Test harness with unit / api / integration split
- [x] GitHub Actions running ruff and pytest against Postgres 16
- [x] Install PostgreSQL 16 and start it
- [x] Create the `sukuu` and `sukuu_test` databases and role
- [x] Fill in `.env` with a real JWT secret (`openssl rand -hex 32`)
- [x] Bump `actions/checkout` and `actions/setup-python` off deprecated Node 20

**Done when** `pytest -m db` runs instead of skipping.

---

## Phase 1 — Data model and migrations

- [ ] Initialise Alembic and wire it to `DATABASE_URL`
- [ ] SQLAlchemy declarative base, engine, and session dependency
- [ ] `users` — email unique, password_hash, role enum, name
- [ ] `classes` — name, academic_year
- [ ] `students` — class_id, parent_id, admission_number unique, status
- [ ] `fee_types` — name, default_amount, billing_period
- [ ] `fee_assignments` — student_id, fee_type_id, amount, due_date, period_label
- [ ] `payments` — fee_assignment_id, amount_paid, method, stripe ids, recorded_by
- [ ] `audit_log` — user_id, action, target, timestamp
- [ ] Every money column `NUMERIC(12,2)`, never float
- [ ] CHECK constraints: amounts strictly positive
- [ ] Indexes on every foreign key you will filter by
- [ ] Generate the first migration, apply it, read the generated SQL
- [ ] Seed script — 4 classes, ~25 students, uneven payment states

> Alembic autogenerate does not reliably notice CHECK constraints or enum changes.
> Read every generated migration before applying it.

**Done when** a dropped database can be rebuilt with `alembic upgrade head` plus the seed script.

---

## Phase 2 — Auth, roles, and the audit trail

Built before the endpoints, not after. Retrofitting authorisation is how permission
bugs get in, and this is the part that carries the security story.

- [ ] Password hashing with bcrypt, plus the 72-byte input guard
- [ ] JWT issue and verify with PyJWT, including expiry
- [ ] `POST /auth/login` and `GET /auth/me`
- [ ] `get_current_user` dependency
- [ ] `require_role(...)` guard covering admin / staff / parent
- [ ] Parent scoping — a parent may only ever read their own children
- [ ] Audit logging on every mutating request
- [ ] Tests covering the full permission matrix, allow and deny
- [ ] Test that parent A gets 403/404 on parent B's child

> Return 404 rather than 403 for records a user may not see. A 403 confirms the record
> exists, which leaks the thing the guard is protecting.

**Done when** every deny case in the permission table has a test that fails if you delete the guard.

---

## Phase 3 — Admin CRUD

- [ ] Pydantic request and response schemas, separate from the models
- [ ] Classes — create, list, update, archive
- [ ] Students — create, list, update, assign to class and parent
- [ ] Fee types — create, list, update
- [ ] Fee assignments — assign to one student
- [ ] Bulk assign a fee to a whole class in one transaction
- [ ] Pagination and filtering on the list endpoints
- [ ] Consistent error shape and validation messages
- [ ] Tests for each resource, happy path and rejection

> Watch the N+1 on any list showing a balance per student. With 25 seeded students it
> looks fine, which is exactly why it survives to the demo.

**Done when** an admin can set up a whole school through the API alone.

---

## Phase 4 — Balances and cash payments

- [x] Pure money logic — outstanding, partial payments, overpayment rejection
- [x] 31 unit tests over the money rules, including rounding and drift
- [ ] Payment service that locks the fee assignment row before writing
- [ ] `POST /payments` for cash, restricted to staff and admin
- [ ] Balance endpoints — per student, per class, per assignment
- [ ] Fill in the concurrency test — two connections, one must lose
- [ ] Every payment records who logged it

> A concurrency test that runs both payments through one session passes whether or not
> the lock exists. It needs two independent connections.

**Done when** the sum of payments can never exceed the fee amount, and you can show why under load.

---

## Phase 5 — Stripe and installments

The account setup lives here rather than in Phase 0 because nothing before this phase
reads a Stripe key, and a `whsec_` secret for local forwarding is printed by `stripe
listen` at the moment you need it — it is not a value you can fetch from the dashboard
in advance.

- [ ] Create a Stripe account and copy the test-mode key into `.env`
- [ ] Install the Stripe CLI for local webhook forwarding
- [ ] `POST /payments/checkout-session` for a chosen amount
- [ ] Validate the requested amount against the balance before creating the session
- [ ] `POST /webhooks/stripe` with signature verification
- [ ] Payments recorded from the webhook, never from the browser redirect
- [ ] Idempotency — store the Stripe event id with a unique constraint
- [ ] Webhook path goes through the same locked payment service
- [ ] End-to-end test locally with `stripe listen`
- [ ] Tests with mocked Stripe payloads, including a replayed event
- [ ] Handle failed and abandoned checkouts without leaving phantom rows

> Verify the signature against the raw request body. FastAPI hands you parsed JSON, and
> re-serialising changes the bytes, so the check fails for reasons that look unrelated.

**Done when** killing the browser mid-payment still results in a correctly recorded payment.

---

## Phase 6 — Frontend

- [ ] Scaffold React + Vite with TypeScript
- [ ] API client with token attachment and 401 handling
- [ ] Auth context, login page, protected routes
- [ ] Admin — students, classes, fee types, assignments
- [ ] Admin dashboard — collected, outstanding, per-class breakdown
- [ ] Staff — outstanding balances, record a cash payment
- [ ] Parent — itemised fees per child with paid and outstanding
- [ ] Parent — pay in full or enter a partial amount
- [ ] Parent — payment history
- [ ] Loading, empty, and error states on every view
- [ ] Currency formatted in one place, never with raw float maths

> Hiding a button the API would refuse is courtesy, not control. If any permission exists
> only in the UI, the security story collapses at the network tab.

**Done when** all three roles can complete their whole job without touching the API docs.

---

## Phase 7 — Deploy

- [ ] Confirm the host offers Python 3.14, or drop to 3.13
- [ ] Managed Postgres provisioned
- [ ] Backend deployed with env vars set and migrations run on release
- [ ] Frontend deployed to Vercel, pointed at the live API
- [ ] CORS locked to the production origin, not `*`
- [ ] Stripe webhook endpoint registered against the deployed URL
- [ ] Demo data seeded, with one login per role
- [ ] Smoke test the full loop in production, including a card payment
- [ ] Confirm no secret was ever committed; rotate anything that leaked

> Demo accounts that let a stranger delete the data leave you with an empty demo the week
> someone actually looks. Reseed on a schedule, or make the public logins read-mostly.

**Done when** a stranger with the URL can log in as all three roles and pay a fee.

---

## Phase 8 — Portfolio polish

The phase people skip. For a project whose purpose is to be read, this is the deliverable.

- [ ] Screenshots or a short demo recording in the README
- [ ] Live demo link and the three demo logins, at the top
- [ ] The Ghana origin story kept short and specific
- [ ] A short decisions section — exact money, row locks, webhook reconciliation
- [ ] One architecture diagram
- [ ] Roadmap section naming what was cut and why
- [ ] Production note on Paystack and Flutterwave for the real market
- [ ] Coverage on the money and permission code specifically
- [ ] Readable commit history — it is part of what gets reviewed

**Done when** someone who has never met you understands the problem, the solution, and the
judgement calls in under two minutes.
