# Build roadmap

Every task between the current repository and a deployed, demo-ready project.

Phases are numbered because they are a dependency chain, not a preference: the payment
work cannot start before the models exist, and the models should not be written before
the role guards do.

**Blocking everything after Phase 0:** PostgreSQL is not installed. Nothing in Phases 1-5
can be written or tested locally until it is.

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
- [x] Create a Stripe account and copy the test-mode keys (webhook secret still pending `stripe listen`)
- [x] Install the Stripe CLI for local webhook forwarding
- [x] Bump `actions/checkout` and `actions/setup-python` off deprecated Node 20

**Done when** `pytest -m db` runs instead of skipping.

---

## Phase 1 — Data model and migrations

- [x] Initialise Alembic and wire it to `DATABASE_URL`
- [x] SQLAlchemy declarative base, engine, and session dependency
- [x] `users` — email unique, password_hash, role enum, name
- [x] `classes` — name, academic_year
- [x] `students` — class_id, parent_id, admission_number unique, status
- [x] `fee_types` — name, default_amount, billing_period
- [x] `fee_assignments` — student_id, fee_type_id, amount, due_date, period_label
- [x] `payments` — fee_assignment_id, amount_paid, method, stripe ids, recorded_by
- [x] `audit_log` — user_id, action, target, timestamp
- [x] Every money column `NUMERIC(12,2)`, never float
- [x] CHECK constraints: amounts strictly positive
- [x] Indexes on every foreign key you will filter by
- [x] Generate the first migration, apply it, read the generated SQL
- [x] Seed script — 4 classes, ~25 students, uneven payment states

> Alembic autogenerate does not reliably notice CHECK constraints or enum changes.
> Read every generated migration before applying it.

**Done when** a dropped database can be rebuilt with `alembic upgrade head` plus the seed script.

---

## Phase 2 — Auth, roles, and the audit trail

Built before the endpoints, not after. Retrofitting authorisation is how permission
bugs get in, and this is the part that carries the security story.

- [x] Password hashing with bcrypt, plus the 72-byte input guard
- [x] JWT issue and verify with PyJWT, including expiry
- [x] `POST /auth/login` and `GET /auth/me`
- [x] `get_current_user` dependency
- [x] `require_role(...)` guard covering admin / staff / parent
- [x] Parent scoping — a parent may only ever read their own children
- [x] Audit logging on every mutating request
- [x] Tests covering the full permission matrix, allow and deny
- [x] Test that parent A gets 403/404 on parent B's child
- [x] Rate limit failed logins, per account and per source address

> The login limiter counts rows in `audit_log`, so the count is shared across
> workers. An in-memory counter gives an attacker one full allowance per process.

> Return 404 rather than 403 for records a user may not see. A 403 confirms the record
> exists, which leaks the thing the guard is protecting.

**Done when** every deny case in the permission table has a test that fails if you delete the guard.

---

## Phase 3 — Admin CRUD

- [x] Pydantic request and response schemas, separate from the models
- [x] Classes — create, list, update, archive
- [x] Students — create, list, update, assign to class and parent
- [x] Fee types — create, list, update
- [x] Fee assignments — assign to one student
- [x] Bulk assign a fee to a whole class in one transaction
- [x] Pagination and filtering on the list endpoints
- [x] Consistent error shape and validation messages
- [x] Tests for each resource, happy path and rejection

> Watch the N+1 on any list showing a balance per student. With 25 seeded students it
> looks fine, which is exactly why it survives to the demo.

> Each list endpoint has a test asserting its query count stays flat between a small
> page and a large one. An N+1 is a count that tracks the result size, so comparing two
> page sizes catches it without hard-coding a number that shifts whenever a route grows
> a join.

> `detail` is always a sentence; field errors arrive beside it under `errors`. Money
> crosses the wire as a string — a JSON number is a double once a browser parses it.

> No update or delete on fee assignments. The amount is what a student was billed and
> payments point at it; changing it belongs with the locked payment service, not a CRUD
> handler.

**Done when** an admin can set up a whole school through the API alone. ✅

---

## Phase 4 — Balances and cash payments

- [x] Pure money logic — outstanding, partial payments, overpayment rejection
- [x] 31 unit tests over the money rules, including rounding and drift
- [x] Payment service that locks the fee assignment row before writing
- [x] Parent-scoped fee list per child — deferred from Phase 3, it belongs with balances
- [x] `POST /payments` for cash, restricted to staff and admin
- [x] Balance endpoints — per student, per class, per assignment
- [x] Fill in the concurrency test — two connections, one must lose
- [x] Every payment records who logged it

> A concurrency test that runs both payments through one session passes whether or not
> the lock exists. It needs two independent connections.

> The lock goes on the fee assignment, not the payments. The dangerous write is a *new*
> row, and a row that does not exist yet cannot be locked. Existing payments are read
> **after** the lock is taken — a total gathered before the wait is a total from before
> the other transaction committed.

> Totalling billed and paid across students → assignments → payments fans out: each bill
> counts once per payment against it. It agrees with a hand-check for everyone who paid
> in one go and is wrong only for installments, which is the feature the product is built
> around. Payments are collapsed to one row per assignment in a subquery first.

> Both defences were verified by breaking them: with `.with_for_update()` removed the
> concurrency test fails, and with the naive join the class total reads 600.00 instead of
> 300.00. A test that passes either way is not a test.

> `POST /payments` takes no `method` from the client. Staff filing a payment as "stripe"
> with no Stripe transaction behind it is the one lie this ledger must not be able to tell.

**Done when** the sum of payments can never exceed the fee amount, and you can show why under load. ✅

---

## Phase 5 — Stripe and installments

- [x] `POST /payments/checkout-session` for a chosen amount
- [x] Validate the requested amount against the balance before creating the session
- [x] `POST /webhooks/stripe` with signature verification
- [x] Payments recorded from the webhook, never from the browser redirect
- [x] Idempotency — store the Stripe event id with a unique constraint
- [x] Webhook path goes through the same locked payment service
- [x] End-to-end test locally with `stripe listen`
- [x] Tests with mocked Stripe payloads, including a replayed event
- [x] Handle failed and abandoned checkouts without leaving phantom rows

> Verify the signature against the raw request body. FastAPI hands you parsed JSON, and
> re-serialising changes the bytes, so the check fails for reasons that look unrelated.

> Test signatures are generated with the real HMAC scheme rather than patching
> `construct_event`. Mocking it out would leave the only security control on an
> unauthenticated endpoint untested — including the tampered-body and stale-timestamp cases.

> Answer 200 for anything final: an unhandled event type, a duplicate, a payment that
> cannot be applied. Stripe retries non-2xx for days, which is right for "the database was
> down" and wrong for everything else. The only 400 is a signature that does not verify.

> An `IntegrityError` at the webhook's commit is only a duplicate if the constraint is
> `stripe_event_id`. Treating any of them as one would answer "already recorded", stop the
> retries, and lose the money behind a 200.

> Money that arrives but cannot be applied — a bursar recorded cash mid-checkout — is not a
> 409. The card is already charged and there is no smaller amount to retry, so it is audited
> as `payment.stripe_needs_refund` for a human. Production would call Stripe's refund API.

> Verified live, not only against generated signatures: `stripe listen` forwarding a real
> `stripe trigger checkout.session.completed`, which Stripe signed. The payment recorded
> against the bill named in the session metadata, and `stripe events resend` of the same
> event answered 200 and left exactly one payment row. Every event type the trigger emits
> along the way — `payment_intent.created`, `charge.succeeded`, `charge.updated` — answered
> 200 as an unhandled type rather than provoking retries.

> Stripe does not operate in Ghana; test mode charges in USD. The transferable part is the
> money rules and the reconciliation, not the processor — see the Paystack note in Phase 8.

**Done when** killing the browser mid-payment still results in a correctly recorded payment. ✅

---

## Phase 6 — Frontend

- [x] Three endpoints the frontend needed and the API did not have:
      `GET /me/children` (a parent had no way to discover their own children),
      `GET /reports/summary` (per-class totals in one query, not an N+1 in the browser),
      and `GET /users?role=parent` (attaching a student to a parent needed a picker)

> **Known gap, named rather than worked around:** there is no way to open a user account
> through the API. Parent and staff accounts arrive through the seed script, so an admin
> cannot onboard a new family end to end. Doing it properly needs user creation, an invite,
> and a password-set flow — a bigger piece of work than the picker that exposed it, and
> not something to smuggle in behind one. Carried to the backlog in Phase 8.
- [x] Scaffold React + Vite with TypeScript
- [x] API client with token attachment and 401 handling
- [x] Auth context, login page, protected routes
- [x] Admin — students, classes, fee types, assignments
- [x] Admin dashboard — collected, outstanding, per-class breakdown
- [x] Staff — outstanding balances, record a cash payment
- [x] Parent — itemised fees per child with paid and outstanding
- [x] Parent — pay in full or enter a partial amount
- [x] Parent — payment history
- [x] Loading, empty, and error states on every view
- [x] Currency formatted in one place, never with raw float maths

> Hiding a button the API would refuse is courtesy, not control. If any permission exists
> only in the UI, the security story collapses at the network tab.

> Loading, empty and error are one component, used by every list. That is what stops the
> third one being the one forgotten on the fifth page.

> Two 401s are not the same. A token that expired mid-session drops the session and returns
> to the login page; a wrong password at that page is a failed attempt and must clear
> nothing. The difference is whether a token was sent at all.

> The payment form is shared by the bursar taking cash and the parent paying by card. The
> rules are the API's, and writing them twice is how two screens end up disagreeing about
> whether 0.00 is a payment. Its client-side checks are a courtesy — the server validates
> again against a balance that may have moved, and its refusal is what gets shown.

**Done when** all three roles can complete their whole job without touching the API docs. ✅

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
