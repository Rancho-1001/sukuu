/**
 * Every payment the school has taken.
 *
 * The "reports" half of the spec's "view all payments & reports", and the
 * place where "every payment records who logged it" is actually visible: a
 * cash payment names the bursar who took it, a card payment names nobody
 * because a webhook is not a person.
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import { Amount, Badge, Card, CardHeader, DataState, Pager, Select, Table, Td, Th } from "../../components/ui";
import { useClasses, usePayments } from "../../lib/queries";

const PAGE_SIZE = 25;

export function PaymentsPage() {
  const [classId, setClassId] = useState<number | undefined>();
  const [method, setMethod] = useState<string | undefined>();
  const [offset, setOffset] = useState(0);

  const classes = useClasses({ limit: 200 });
  const { data, isPending, error } = usePayments({
    class_id: classId,
    method,
    limit: PAGE_SIZE,
    offset,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Payments</h1>
        <p className="mt-1 text-sm text-slate-500">
          Everything received, most recent first, with who recorded it.
        </p>
      </div>

      <Card>
        <CardHeader
          title="All payments"
          subtitle={data ? `${data.total} matching` : undefined}
          actions={
            <>
              <Select
                aria-label="Filter by class"
                value={classId ?? ""}
                onChange={(event) => {
                  setClassId(event.target.value ? Number(event.target.value) : undefined);
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
              <Select
                aria-label="Filter by method"
                value={method ?? ""}
                onChange={(event) => {
                  setMethod(event.target.value || undefined);
                  setOffset(0);
                }}
              >
                <option value="">Cash and card</option>
                <option value="cash">Cash only</option>
                <option value="stripe">Card only</option>
              </Select>
            </>
          }
        />
        <DataState
          isPending={isPending}
          error={error}
          isEmpty={data?.items.length === 0}
          emptyMessage="No payments match."
        >
          <Table
            head={
              <tr>
                <Th>Date</Th>
                <Th>Student · fee</Th>
                <Th>Method</Th>
                <Th>Recorded by</Th>
                <Th align="right">Amount</Th>
              </tr>
            }
          >
            {data?.items.map((payment) => (
              <tr key={payment.id}>
                <Td label="Date">{new Date(payment.paid_at).toLocaleString()}</Td>
                <Td label="Student · fee">
                  <Link
                    to={`/students/${payment.fee_assignment.student.id}`}
                    className="font-medium text-slate-900 hover:text-indigo-600"
                  >
                    {payment.fee_assignment.student.full_name}
                  </Link>
                  <span className="block text-xs text-slate-500">
                    {payment.fee_assignment.fee_type.name} · {payment.fee_assignment.period_label}
                  </span>
                </Td>
                <Td label="Method">
                  <Badge tone={payment.method === "stripe" ? "slate" : "amber"}>
                    {payment.method === "stripe" ? "Card" : "Cash"}
                  </Badge>
                </Td>
                <Td label="Recorded by">
                  {payment.recorded_by?.name ?? <span className="text-slate-400">Online</span>}
                </Td>
                <Td label="Amount" align="right" className="font-medium">
                  <Amount value={payment.amount_paid} />
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
