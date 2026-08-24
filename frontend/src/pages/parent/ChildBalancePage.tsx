import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { PayForm } from "../../components/PayForm";
import {
  Amount,
  Badge,
  Button,
  Card,
  CardHeader,
  DataState,
  Table,
  Td,
  Th,
} from "../../components/ui";
import { useStartCheckout, useStudentBalance, useStudentPayments } from "../../lib/queries";
import type { FeeAssignment } from "../../lib/types";
import { Totals } from "./MyChildrenPage";

export function ChildBalancePage() {
  const { studentId } = useParams();
  const id = Number(studentId);
  const { data: balance, isPending, error } = useStudentBalance(
    Number.isFinite(id) ? id : undefined,
  );
  const [payingId, setPayingId] = useState<number | null>(null);

  return (
    <div className="space-y-6">
      <div>
        <Link to="/my-children" className="text-sm text-indigo-600 hover:underline">
          ← All children
        </Link>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">
          {balance?.student.full_name ?? "Fees"}
        </h1>
        {balance?.school_class ? (
          <p className="mt-1 text-sm text-slate-500">{balance.school_class.name}</p>
        ) : null}
      </div>

      <DataState isPending={isPending} error={error}>
        {balance ? (
          <div className="space-y-6">
            <Totals billed={balance.billed} paid={balance.paid} outstanding={balance.outstanding} />

            <Card>
              <CardHeader title="Fees" subtitle="Pay in full, or enter a smaller amount." />
              {balance.lines.length === 0 ? (
                <p className="px-5 py-10 text-center text-sm text-slate-500">
                  Nothing has been billed yet.
                </p>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {balance.lines.map((line) => (
                    <FeeLine
                      key={line.id}
                      line={line}
                      isPaying={payingId === line.id}
                      onPay={() => setPayingId(line.id)}
                      onCancel={() => setPayingId(null)}
                    />
                  ))}
                </ul>
              )}
            </Card>

            <PaymentHistory studentId={id} />
          </div>
        ) : null}
      </DataState>
    </div>
  );
}

function FeeLine({
  line,
  isPaying,
  onPay,
  onCancel,
}: {
  line: FeeAssignment;
  isPaying: boolean;
  onPay: () => void;
  onCancel: () => void;
}) {
  const checkout = useStartCheckout();

  return (
    <li className="px-5 py-4">
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
              <Amount value={line.amount_paid} /> of <Amount value={line.amount} /> paid
            </p>
            <p className="font-semibold text-slate-900">
              <Amount value={line.outstanding} /> owed
            </p>
          </div>
          {line.settled ? <Badge tone="green">Paid</Badge> : isPaying ? null : <Button onClick={onPay}>Pay</Button>}
        </div>
      </div>

      {isPaying && !line.settled ? (
        <div className="mt-4 max-w-sm rounded-lg bg-slate-50 p-4">
          <PayForm
            outstanding={line.outstanding}
            submitLabel="Continue to payment"
            busyLabel="Opening payment page…"
            onCancel={onCancel}
            onSubmit={async (amount) => {
              const session = await checkout.mutateAsync({ fee_assignment_id: line.id, amount });
              // Stripe's hosted page takes it from here. Nothing is recorded
              // until the webhook arrives, so closing the tab at this point
              // loses nothing and the payment still lands.
              window.location.assign(session.checkout_url);
            }}
          />
          <p className="mt-3 text-xs text-slate-500">
            You will be taken to Stripe to pay by card. Test mode — no real money moves.
          </p>
        </div>
      ) : null}
    </li>
  );
}

function PaymentHistory({ studentId }: { studentId: number }) {
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
              <Td>{new Date(payment.paid_at).toLocaleDateString()}</Td>
              <Td>
                <Badge tone={payment.method === "stripe" ? "slate" : "amber"}>
                  {payment.method === "stripe" ? "Card" : "Cash"}
                </Badge>
              </Td>
              <Td>{payment.recorded_by?.name ?? "Online"}</Td>
              <Td align="right" className="font-medium">
                <Amount value={payment.amount_paid} />
              </Td>
            </tr>
          ))}
        </Table>
      </DataState>
    </Card>
  );
}
