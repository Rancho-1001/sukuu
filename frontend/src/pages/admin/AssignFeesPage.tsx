/**
 * Charging fees: one student, or a whole class.
 *
 * The bulk form is the one that matters — "tuition, Term 1, Grade 5B" is the
 * job an administrator actually does in August. It reports what it did rather
 * than just succeeding, because re-running it after a student joins mid-term
 * is normal and the result is the only way to see that only the new child was
 * charged.
 */

import { useState } from "react";

import { FormCard } from "../../components/FormCard";
import {
  Amount,
  Badge,
  Card,
  CardHeader,
  DataState,
  Field,
  Input,
  Pager,
  Select,
  Table,
  Td,
  Th,
} from "../../components/ui";
import { formatMoney } from "../../lib/money";
import {
  useAssignFee,
  useAssignments,
  useBulkAssignFee,
  useClasses,
  useFeeTypes,
  useStudents,
} from "../../lib/queries";

const PAGE_SIZE = 25;

export function AssignFeesPage() {
  const [offset, setOffset] = useState(0);
  const [classFilter, setClassFilter] = useState<number | undefined>();

  const classes = useClasses({ limit: 200 });
  const feeTypes = useFeeTypes({ limit: 200 });
  const students = useStudents({ limit: 200 });
  const assignOne = useAssignFee();
  const assignClass = useBulkAssignFee();

  const { data, isPending, error } = useAssignments({
    class_id: classFilter,
    limit: PAGE_SIZE,
    offset,
  });

  const feeTypeOptions = feeTypes.data?.items ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Fees</h1>
        <p className="mt-1 text-sm text-slate-500">
          Charge a whole class at once, or one student at a time.
        </p>
      </div>

      <FormCard
        title="Charge a class"
        subtitle="Every active student in the class. Anyone already charged for this period is skipped."
        openLabel="Charge a class"
        submitLabel="Charge class"
        onSubmit={async (form) => {
          const result = await assignClass.mutateAsync({
            class_id: Number(form.get("class_id")),
            fee_type_id: Number(form.get("fee_type_id")),
            period_label: String(form.get("period_label") ?? ""),
            amount: String(form.get("amount") ?? "") || undefined,
            due_date: String(form.get("due_date") ?? "") || null,
          });
          const skipped = result.skipped_student_ids.length;
          return (
            `Charged ${result.created} student${result.created === 1 ? "" : "s"} ` +
            `${formatMoney(result.amount)}` +
            (skipped ? `. ${skipped} already had this fee for the period.` : ".")
          );
        }}
      >
        {(error) => (
          <>
            <Field label="Class" error={error?.fieldError("class_id")}>
              <Select name="class_id" required defaultValue="">
                <option value="" disabled>
                  Choose a class
                </option>
                {classes.data?.items.map((schoolClass) => (
                  <option key={schoolClass.id} value={schoolClass.id}>
                    {schoolClass.name} · {schoolClass.active_student_count} students
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Fee type" error={error?.fieldError("fee_type_id")}>
              <Select name="fee_type_id" required defaultValue="">
                <option value="" disabled>
                  Choose a fee
                </option>
                {feeTypeOptions.map((feeType) => (
                  <option key={feeType.id} value={feeType.id}>
                    {feeType.name} · {feeType.default_amount}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Period" error={error?.fieldError("period_label")}>
              <Input name="period_label" placeholder="Term 1 2026" required />
            </Field>
            <Field
              label="Amount"
              error={error?.fieldError("amount")}
              hint="Leave empty to use the fee's default"
            >
              <Input name="amount" inputMode="decimal" placeholder="250.00" />
            </Field>
            <Field label="Due date" error={error?.fieldError("due_date")}>
              <Input name="due_date" type="date" />
            </Field>
          </>
        )}
      </FormCard>

      <FormCard
        title="Charge one student"
        subtitle="For a fee that is not class-wide — a scholarship rate, or arrears."
        openLabel="Charge a student"
        submitLabel="Charge student"
        onSubmit={async (form) => {
          const created = await assignOne.mutateAsync({
            student_id: Number(form.get("student_id")),
            fee_type_id: Number(form.get("fee_type_id")),
            period_label: String(form.get("period_label") ?? ""),
            amount: String(form.get("amount") ?? "") || undefined,
            due_date: String(form.get("due_date") ?? "") || null,
          });
          return `${created.student.full_name} charged ${formatMoney(created.amount)}.`;
        }}
      >
        {(error) => (
          <>
            <Field label="Student" error={error?.fieldError("student_id")}>
              <Select name="student_id" required defaultValue="">
                <option value="" disabled>
                  Choose a student
                </option>
                {students.data?.items.map((student) => (
                  <option key={student.id} value={student.id}>
                    {student.full_name} · {student.admission_number}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Fee type" error={error?.fieldError("fee_type_id")}>
              <Select name="fee_type_id" required defaultValue="">
                <option value="" disabled>
                  Choose a fee
                </option>
                {feeTypeOptions.map((feeType) => (
                  <option key={feeType.id} value={feeType.id}>
                    {feeType.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Period" error={error?.fieldError("period_label")}>
              <Input name="period_label" placeholder="Term 1 2026" required />
            </Field>
            <Field label="Amount" error={error?.fieldError("amount")} hint="Leave empty for the default">
              <Input name="amount" inputMode="decimal" placeholder="250.00" />
            </Field>
            <Field label="Due date" error={error?.fieldError("due_date")}>
              <Input name="due_date" type="date" />
            </Field>
          </>
        )}
      </FormCard>

      <Card>
        <CardHeader
          title="Assigned fees"
          subtitle={data ? `${data.total} total` : undefined}
          actions={
            <Select
              aria-label="Filter by class"
              value={classFilter ?? ""}
              onChange={(event) => {
                setClassFilter(event.target.value ? Number(event.target.value) : undefined);
                setOffset(0);
              }}
            >
              <option value="">All classes</option>
              {classes.data?.items.map((schoolClass) => (
                <option key={schoolClass.id} value={schoolClass.id}>
                  {schoolClass.name}
                </option>
              ))}
            </Select>
          }
        />
        <DataState
          isPending={isPending}
          error={error}
          isEmpty={data?.items.length === 0}
          emptyMessage="No fees assigned yet."
        >
          <Table
            head={
              <tr>
                <Th>Student</Th>
                <Th>Fee</Th>
                <Th align="right">Amount</Th>
                <Th align="right">Owed</Th>
              </tr>
            }
          >
            {data?.items.map((line) => (
              <tr key={line.id}>
                <Td>
                  <span className="font-medium text-slate-900">{line.student.full_name}</span>
                </Td>
                <Td>
                  {line.fee_type.name}
                  <span className="ml-2 text-slate-400">{line.period_label}</span>
                </Td>
                <Td align="right">
                  <Amount value={line.amount} />
                </Td>
                <Td align="right">
                  {line.settled ? (
                    <Badge tone="green">Paid</Badge>
                  ) : (
                    <span className="font-medium">
                      <Amount value={line.outstanding} />
                    </span>
                  )}
                </Td>
              </tr>
            ))}
          </Table>
          <Pager total={data?.total ?? 0} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
        </DataState>
      </Card>
    </div>
  );
}
