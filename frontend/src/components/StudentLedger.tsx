/**
 * One student's fees and payments.
 *
 * The parent's view and the bursar's view of a child are the same ledger
 * with one difference: what the button on an unpaid line does. A parent is
 * sent to the payment processor; a bursar records cash. That is a render prop, and
 * everything else - totals, lines, history - is shared so the two screens
 * cannot drift apart on how a balance is presented.
 */

import type { ReactNode } from "react";

import { MethodBadge } from "./MethodBadge";
import { Amount, Badge, Card, CardHeader, DataState, Table, Td, Th } from "./ui";
import { useStudentBalance, useStudentPayments } from "../lib/queries";
import type { FeeAssignment, StudentBalance } from "../lib/types";

export function Totals({
  billed,
  paid,
  outstanding,
}: {
  billed: string;
  paid: string;
  outstanding: string;
}) {
  const cells = [
    { label: "Billed", value: billed, tone: "text-slate-900" },
    { label: "Paid", value: paid, tone: "text-emerald-700" },
    { label: "Outstanding", value: outstanding, tone: "text-slate-900" },
  ];
  return (
    <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      {cells.map((cell) => (
        <Card key={cell.label} className="px-5 py-4">
          <dt className="text-sm text-slate-500">{cell.label}</dt>
          <dd className={`mt-1 text-2xl font-semibold ${cell.tone}`}>
            <Amount value={cell.value} />
          </dd>
        </Card>
      ))}
    </dl>
  );
}

export function StudentLedger({
  studentId,
  subtitle,
  renderAction,
  renderExpanded,
  expandedId,
}: {
  studentId: number;
  subtitle: string;
  /** What sits on the right of an unpaid line. */
  renderAction: (line: FeeAssignment) => ReactNode;
  /** Optional: content shown beneath the line with `expandedId`. */
  renderExpanded?: (line: FeeAssignment) => ReactNode;
  expandedId?: number | null;
}) {
  const balance = useStudentBalance(studentId);

  return (
    <DataState isPending={balance.isPending} error={balance.error}>
      {balance.data ? (
        <div className="space-y-6">
          <Totals
            billed={balance.data.billed}
            paid={balance.data.paid}
            outstanding={balance.data.outstanding}
          />

          <Card>
            <CardHeader title="Fees" subtitle={subtitle} />
            {balance.data.lines.length === 0 ? (
              <p className="px-5 py-10 text-center text-sm text-slate-500">
                Nothing has been billed yet.
              </p>
            ) : (
              <ul className="divide-y divide-slate-100">
                {balance.data.lines.map((line) => (
                  <li key={line.id} className="px-5 py-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <p className="font-medium text-slate-900">{line.fee_type.name}</p>
                        <p className="text-sm text-slate-500">
                          {line.period_label}
                          {line.due_date ? ` · due ${line.due_date}` : ""}
                        </p>
                      </div>
                      <div className="flex items-center gap-4 text-sm">
                        <div className="text-right">
                          <p className="text-slate-500">
                            <Amount value={line.amount_paid} /> of <Amount value={line.amount} />{" "}
                            paid
                          </p>
                          <p className="font-semibold text-slate-900">
                            <Amount value={line.outstanding} /> owed
                          </p>
                        </div>
                        {line.settled ? <Badge tone="green">Paid</Badge> : renderAction(line)}
                      </div>
                    </div>
                    {renderExpanded && expandedId === line.id && !line.settled
                      ? renderExpanded(line)
                      : null}
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <PaymentHistory studentId={studentId} />
        </div>
      ) : null}
    </DataState>
  );
}

export function PaymentHistory({ studentId }: { studentId: number }) {
  const { data, isPending, error } = useStudentPayments(studentId);

  return (
    <Card>
      <CardHeader title="Payment history" />
      <DataState
        isPending={isPending}
        error={error}
        isEmpty={data?.items.length === 0}
        emptyMessage="No payments yet."
      >
        <Table
          head={
            <tr>
              <Th>Date</Th>
              <Th>Method</Th>
              <Th>Recorded by</Th>
              <Th align="right">Amount</Th>
            </tr>
          }
        >
          {data?.items.map((payment) => (
            <tr key={payment.id}>
              <Td label="Date">{new Date(payment.paid_at).toLocaleDateString()}</Td>
              <Td label="Method">
                <MethodBadge method={payment.method} />
              </Td>
              <Td label="Recorded by">{payment.recorded_by?.name ?? "Online"}</Td>
              <Td label="Amount" align="right" className="font-medium">
                <Amount value={payment.amount_paid} />
              </Td>
            </tr>
          ))}
        </Table>
      </DataState>
    </Card>
  );
}

export type { StudentBalance };
