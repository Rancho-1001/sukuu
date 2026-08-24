/**
 * The API's shapes, by hand.
 *
 * Generated clients drift the moment someone edits a schema without
 * regenerating, and the surface here is small enough that writing it out is
 * cheaper than owning a codegen step. Every `Money` below is a string on
 * purpose - see `money.ts` for why.
 */

/** An amount, as the API sends it: `"250.00"`. Never do arithmetic on this. */
export type Money = string;

export type UserRole = "admin" | "staff" | "parent";
export type StudentStatus = "active" | "inactive";
export type BillingPeriod = "term" | "monthly" | "one_time";
export type PaymentMethod = "cash" | "stripe";

export interface User {
  id: number;
  email: string;
  name: string;
  role: UserRole;
}

export interface Token {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface ClassSummary {
  id: number;
  name: string;
  academic_year: string;
}

export interface SchoolClass extends ClassSummary {
  archived_at: string | null;
  active_student_count: number;
}

export interface ParentSummary {
  id: number;
  name: string;
  email: string;
}

export interface StudentSummary {
  id: number;
  full_name: string;
  admission_number: string;
}

export interface Student extends StudentSummary {
  first_name: string;
  last_name: string;
  status: StudentStatus;
  school_class: ClassSummary | null;
  parent: ParentSummary | null;
}

export interface FeeTypeSummary {
  id: number;
  name: string;
  billing_period: BillingPeriod;
}

export interface FeeType extends FeeTypeSummary {
  description: string | null;
  default_amount: Money;
}

export interface FeeAssignment {
  id: number;
  amount: Money;
  amount_paid: Money;
  outstanding: Money;
  settled: boolean;
  due_date: string | null;
  period_label: string;
  student: StudentSummary;
  fee_type: FeeTypeSummary;
}

export interface BulkAssignmentResult {
  class_id: number;
  fee_type_id: number;
  period_label: string;
  amount: Money;
  created: number;
  skipped_student_ids: number[];
}

export interface Payment {
  id: number;
  fee_assignment_id: number;
  amount_paid: Money;
  method: PaymentMethod;
  paid_at: string;
  recorded_by: { id: number; name: string } | null;
}

export interface CashPaymentReceipt {
  payment: Payment;
  fee_assignment: FeeAssignment;
}

export interface StudentBalance {
  student: StudentSummary;
  school_class: ClassSummary | null;
  parent: ParentSummary | null;
  billed: Money;
  paid: Money;
  outstanding: Money;
  lines: FeeAssignment[];
}

export interface StudentBalanceRow {
  student: StudentSummary;
  billed: Money;
  paid: Money;
  outstanding: Money;
}

export interface ClassBalance {
  school_class: ClassSummary;
  billed: Money;
  paid: Money;
  outstanding: Money;
  students: Page<StudentBalanceRow>;
}

export interface CheckoutSession {
  session_id: string;
  checkout_url: string;
  fee_assignment_id: number;
  amount: Money;
}

/** One field the API objected to, from its `errors` array. */
export interface FieldError {
  field: string;
  message: string;
}

export interface ClassCollectionRow {
  school_class: ClassSummary;
  billed: Money;
  paid: Money;
  outstanding: Money;
}

export interface SchoolSummary {
  billed: Money;
  paid: Money;
  outstanding: Money;
  /**
   * Will not always sum to the totals above: a student enrolled but not yet
   * placed in a class is billed like anyone else and has no class row to sit
   * in. The gap means somebody needs placing.
   */
  classes: ClassCollectionRow[];
}
