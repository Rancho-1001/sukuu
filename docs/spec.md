# Sukuu — School Fee Management System
### Project Specification & Brainstorm (v1)

> **One-line pitch:** A school management platform that lets administrators track student fees (tuition, feeding, uniforms), lets parents pay online and in installments, and gives staff a clean view of who owes what.

> **Origin story (for interviews):** Built after teaching in Ghana, where fee and feeding-payment tracking was often manual and error-prone. Sukuu ("school" in Twi/Akan) solves a real problem in an underserved market.

---

## 1. What this project proves to recruiters

This is the flagship portfolio project, deliberately designed to tell **three stories at once**:

- **Full-stack + payments competence** — React frontend, real backend/API, Postgres, Stripe integration. The checkboxes recruiters scan for.
- **Security / access-control depth** — three roles with real permission boundaries, JWT auth, and an audit log. Leans on Security+ and CSE 425 background.
- **Solving a real problem I lived** — genuine origin story from teaching in Ghana; not a tutorial clone.

Keep all three visible in the README and the demo.

---

## 2. Core loop (the whole product for v1)

```
Admin sets up school (students, classes, fee types)
   → assigns fees to students
      → parents/staff see what's owed
         → payments recorded (online via Stripe, or cash by staff)
            → dashboard shows paid vs. outstanding
```

Nothing that breaks this loop goes in v1. Everything else is a roadmap item.

---

## 3. Roles & permissions

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

The permission boundaries are the security showcase — enforce them in backend middleware, not just the UI.

---

## 4. Features by role

**Admin**
- Create/edit students, assign to a class
- Define fee types (tuition, feeding, uniform, etc.) with amount + billing period
- Assign fees to individual students or a whole class at once
- Dashboard: total collected / total outstanding / per-class breakdown

**Parent**
- See each child's itemized fees with paid/outstanding status
- Pay outstanding fees online (Stripe test mode)
- **Pay in installments / partial payments** (v1 UI feature)
- View payment history

**Staff/Bursar**
- Record cash/offline payments against a student's fee
- View outstanding balances across students
- Cannot touch the fee structure

---

## 5. Data schema (7 tables)

**users** — id, email, password_hash, role (admin/staff/parent), name, created_at

**students** — id, first_name, last_name, class_id (FK), parent_id (FK → users), admission_number, status (active/inactive)

**classes** — id, name (e.g. "Grade 5B"), academic_year

**fee_types** — id, name (tuition/feeding/uniform), description, default_amount, billing_period (term/monthly/one-time)
- *Note: feeding is handled as just another fee_type in v1 (simplest). Prepaid top-up model is a roadmap idea.*

**fee_assignments** — id, student_id (FK), fee_type_id (FK), amount, due_date, period_label (e.g. "Term 1 2026")
- *The "student owes X for Y" record — the heart of the app.*

**payments** — id, fee_assignment_id (FK), amount_paid, payment_method (stripe/cash), stripe_payment_id (nullable), recorded_by (FK → users), paid_at

**audit_log** — id, user_id, action, target, timestamp
- *Quiet security flex — shows accountability thinking. Build if time allows.*

### Key relationships
- A parent (user) has many students
- A student belongs to one class, has many fee_assignments
- A fee_assignment can have **many** payments (this is what enables installments)
- Every payment records who logged it (recorded_by)

### Outstanding-balance logic (the detail that matters)
```
outstanding = fee_assignment.amount − SUM(payments.amount_paid)
```
- Support **partial payments** (multiple payments per fee_assignment)
- **Reject overpayment** — don't let SUM(payments) exceed the fee amount
- This small piece of financial correctness is what makes a junior look senior

---

## 6. Suggested stack

- **Backend:** FastAPI (Python) or Node/Express
- **Database:** Postgres
- **Frontend:** React
- **Auth:** JWT with role-based middleware
- **Payments:** Stripe test mode
- **Deploy:** Railway/Render (backend + DB) + Vercel (frontend)

---

## 7. Build order (weeks 1-3)

1. **Week 1** — Schema + admin CRUD (students, classes, fee types, assignments). Get the data model solid first.
2. **Week 2** — Auth + role-based access control. Lock down the three roles in middleware.
3. **Week 3** — Parent payment flow + Stripe + installments + dashboard. This is the riskiest part, so tackle it when everything else is stable.

---

## 8. Explicitly cut from v1 (README "roadmap" section)

Naming these shows product judgment without building them:

- Attendance tracking
- Grades / report cards
- Timetables / scheduling
- SMS / email fee reminders *(most obvious next feature)*
- Multi-school / multi-tenant support
- Refunds & reversals
- Feeding as a prepaid top-up balance
- Localized payment gateways (Paystack / Flutterwave for African markets)

---

## 9. Production-reality notes (README credibility)

- **Payment gateway:** Stripe doesn't operate in Ghana directly. Demo uses Stripe USD test mode (standard for portfolio projects). A production version for the target market would use **Paystack** or **Flutterwave**. Mentioning this shows you understand the real deployment context.
- **Currency:** Build in USD for the demo; note that production would be locale-aware (GHS).

---

## 10. Open questions to revisit

- [ ] Final name: **Sukuu** (front-runner) vs. Klaso / Skora / FeeLedger
- [ ] Confirm backend: FastAPI vs. Express
- [ ] Does the dashboard need charts (recharts) or are summary cards enough for v1?
- [ ] Seed data: how many students/classes to make the demo feel real? (~20-30 students, 3-4 classes suggested)
