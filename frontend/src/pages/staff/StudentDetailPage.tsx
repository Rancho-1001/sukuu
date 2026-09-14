/**
 * One student, as the office sees them.
 *
 * The same ledger a parent sees for their own child, with two differences: it
 * shows who the parent is, and the button on an unpaid line records cash
 * instead of opening Stripe. The API's per-row guard means a parent who
 * finds this URL still only gets their own children out of it.
 */

import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { PayForm } from "../../components/PayForm";
import { StudentLedger } from "../../components/StudentLedger";
import { Badge, Banner, Button } from "../../components/ui";
import { formatMoney } from "../../lib/money";
import { useRecordCashPayment, useStudent } from "../../lib/queries";

export function StudentDetailPage() {
  const { studentId } = useParams();
  const id = Number(studentId);
  const valid = Number.isFinite(id) && id > 0;
  const student = useStudent(valid ? id : undefined);
  const record = useRecordCashPayment();
  const [payingId, setPayingId] = useState<number | null>(null);
  const [receipt, setReceipt] = useState<string | null>(null);

  return (
    <div className="space-y-6">
      <div>
        <Link to="/students" className="text-sm text-indigo-600 hover:underline">
          ← All students
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            {student.data?.full_name ?? "Student"}
          </h1>
          {student.data?.status === "inactive" ? <Badge tone="slate">Withdrawn</Badge> : null}
        </div>
        {student.data ? (
          <p className="mt-1 text-sm text-slate-500">
            <span className="font-mono text-xs">{student.data.admission_number}</span>
            {" · "}
            {student.data.school_class?.name ?? "No class"}
            {" · "}
            {student.data.parent ? (
              <>
                Parent: {student.data.parent.name}{" "}
                <span className="text-slate-400">({student.data.parent.email})</span>
              </>
            ) : (
              <span className="text-slate-400">No parent linked</span>
            )}
          </p>
        ) : null}
      </div>

      {receipt ? <Banner tone="success">{receipt}</Banner> : null}

      {valid ? (
        <StudentLedger
          studentId={id}
          subtitle="Record a cash payment against any unpaid fee."
          expandedId={payingId}
          renderAction={(line) =>
            payingId === line.id ? null : (
              <Button variant="secondary" onClick={() => setPayingId(line.id)}>
                Record cash
              </Button>
            )
          }
          renderExpanded={(line) => (
            <div className="mt-4 max-w-sm rounded-lg bg-slate-50 p-4">
              <PayForm
                outstanding={line.outstanding}
                submitLabel="Record payment"
                busyLabel="Recording…"
                onCancel={() => setPayingId(null)}
                onSubmit={async (amount) => {
                  const result = await record.mutateAsync({
                    fee_assignment_id: line.id,
                    amount,
                  });
                  setPayingId(null);
                  setReceipt(
                    `Recorded ${formatMoney(result.payment.amount_paid)}. ` +
                      (result.fee_assignment.settled
                        ? "That fee is now settled."
                        : `${formatMoney(result.fee_assignment.outstanding)} still owed.`),
                  );
                }}
              />
            </div>
          )}
        />
      ) : null}
    </div>
  );
}
