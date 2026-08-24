/**
 * Typed queries and mutations.
 *
 * One place per endpoint, so pages describe what they need rather than how to
 * fetch it, and so cache invalidation after a payment is decided once instead
 * of at each call site. Getting that wrong is how a balance stays stale on
 * screen right after somebody paid it.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, query } from "./api";
import type {
  BulkAssignmentResult,
  CashPaymentReceipt,
  CheckoutSession,
  ClassBalance,
  FeeAssignment,
  FeeType,
  Page,
  Payment,
  SchoolClass,
  SchoolSummary,
  Student,
  StudentBalance,
} from "./types";

export const keys = {
  classes: (params?: unknown) => ["classes", params] as const,
  classBalance: (id: number, offset: number) => ["class-balance", id, offset] as const,
  students: (params?: unknown) => ["students", params] as const,
  feeTypes: (params?: unknown) => ["fee-types", params] as const,
  assignments: (params?: unknown) => ["assignments", params] as const,
  studentBalance: (id: number) => ["student-balance", id] as const,
  studentPayments: (id: number) => ["student-payments", id] as const,
  payments: (params?: unknown) => ["payments", params] as const,
  myChildren: () => ["my-children"] as const,
  summary: () => ["summary"] as const,
};

/** The parent's own children. Answered from the token, so it takes no arguments. */
export function useMyChildren() {
  return useQuery({
    queryKey: keys.myChildren(),
    queryFn: () => api.get<Student[]>("/me/children"),
  });
}

export function useSchoolSummary() {
  return useQuery({
    queryKey: keys.summary(),
    queryFn: () => api.get<SchoolSummary>("/reports/summary"),
  });
}

export interface ListParams {
  limit?: number;
  offset?: number;
}

export function useClasses(params: ListParams & { q?: string; include_archived?: boolean } = {}) {
  return useQuery({
    queryKey: keys.classes(params),
    queryFn: () => api.get<Page<SchoolClass>>(`/classes${query({ limit: 50, ...params })}`),
  });
}

export function useStudents(
  params: ListParams & { q?: string; class_id?: number; status?: string; parent_id?: number } = {},
) {
  return useQuery({
    queryKey: keys.students(params),
    queryFn: () => api.get<Page<Student>>(`/students${query({ limit: 25, ...params })}`),
  });
}

export function useFeeTypes(params: ListParams & { q?: string } = {}) {
  return useQuery({
    queryKey: keys.feeTypes(params),
    queryFn: () => api.get<Page<FeeType>>(`/fee-types${query({ limit: 50, ...params })}`),
  });
}

export function useAssignments(
  params: ListParams & {
    class_id?: number;
    student_id?: number;
    fee_type_id?: number;
    period_label?: string;
    outstanding_only?: boolean;
  } = {},
) {
  return useQuery({
    queryKey: keys.assignments(params),
    queryFn: () => api.get<Page<FeeAssignment>>(`/fee-assignments${query({ limit: 25, ...params })}`),
  });
}

export function useStudentBalance(studentId: number | undefined) {
  return useQuery({
    queryKey: keys.studentBalance(studentId!),
    queryFn: () => api.get<StudentBalance>(`/students/${studentId}/balance`),
    enabled: studentId !== undefined,
  });
}

export function useStudentPayments(studentId: number | undefined) {
  return useQuery({
    queryKey: keys.studentPayments(studentId!),
    queryFn: () => api.get<Page<Payment>>(`/students/${studentId}/payments${query({ limit: 50 })}`),
    enabled: studentId !== undefined,
  });
}

export function useClassBalance(classId: number | undefined, offset = 0) {
  return useQuery({
    queryKey: keys.classBalance(classId!, offset),
    queryFn: () => api.get<ClassBalance>(`/classes/${classId}/balance${query({ limit: 25, offset })}`),
    enabled: classId !== undefined,
  });
}

/**
 * Everything a payment could have changed.
 *
 * Money touches a fee assignment, the student's balance, their history, the
 * class roll-up and the dashboard. Listing them here rather than at each call
 * site is the difference between a screen that updates and one that lies until
 * someone reloads.
 */
function invalidateAfterPayment(queryClient: ReturnType<typeof useQueryClient>) {
  for (const key of [
    "assignments",
    "student-balance",
    "student-payments",
    "class-balance",
    "payments",
    "summary",
  ]) {
    void queryClient.invalidateQueries({ queryKey: [key] });
  }
}

export function useRecordCashPayment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { fee_assignment_id: number; amount: string }) =>
      api.post<CashPaymentReceipt>("/payments", body),
    onSuccess: () => invalidateAfterPayment(queryClient),
  });
}

export function useStartCheckout() {
  return useMutation({
    mutationFn: (body: { fee_assignment_id: number; amount: string }) =>
      api.post<CheckoutSession>("/payments/checkout-session", body),
  });
}

export function useCreateClass() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; academic_year: string }) => api.post<SchoolClass>("/classes", body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["classes"] }),
  });
}

export function useArchiveClass() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, archived }: { id: number; archived: boolean }) =>
      api.post<SchoolClass>(`/classes/${id}/${archived ? "restore" : "archive"}`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["classes"] }),
  });
}

export function useCreateFeeType() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      name: string;
      description?: string | null;
      default_amount: string;
      billing_period: string;
    }) => api.post<FeeType>("/fee-types", body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["fee-types"] }),
  });
}

export function useCreateStudent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      first_name: string;
      last_name: string;
      admission_number: string;
      class_id?: number | null;
      parent_id?: number | null;
    }) => api.post<Student>("/students", body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["students"] });
      // A new student changes a class's roll count.
      void queryClient.invalidateQueries({ queryKey: ["classes"] });
    },
  });
}

export function useUpdateStudent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number } & Record<string, unknown>) =>
      api.patch<Student>(`/students/${id}`, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["students"] });
      void queryClient.invalidateQueries({ queryKey: ["classes"] });
    },
  });
}

export function useAssignFee() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      student_id: number;
      fee_type_id: number;
      period_label: string;
      amount?: string;
      due_date?: string | null;
    }) => api.post<FeeAssignment>("/fee-assignments", body),
    onSuccess: () => invalidateAfterPayment(queryClient),
  });
}

export function useBulkAssignFee() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      class_id: number;
      fee_type_id: number;
      period_label: string;
      amount?: string;
      due_date?: string | null;
    }) => api.post<BulkAssignmentResult>("/fee-assignments/bulk", body),
    onSuccess: () => invalidateAfterPayment(queryClient),
  });
}
