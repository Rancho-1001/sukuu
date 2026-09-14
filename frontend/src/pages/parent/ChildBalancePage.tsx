import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { PayForm } from "../../components/PayForm";
import { StudentLedger } from "../../components/StudentLedger";
import { Button } from "../../components/ui";
import { useStartCheckout, useStudentBalance } from "../../lib/queries";

export function ChildBalancePage() {
  const { studentId } = useParams();
  const id = Number(studentId);
  const valid = Number.isFinite(id) && id > 0;
  const { data: balance } = useStudentBalance(valid ? id : undefined);
  const [payingId, setPayingId] = useState<number | null>(null);
  const checkout = useStartCheckout();

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

      {valid ? (
        <StudentLedger
          studentId={id}
          subtitle="Pay in full, or enter a smaller amount."
          expandedId={payingId}
          renderAction={(line) =>
            payingId === line.id ? null : <Button onClick={() => setPayingId(line.id)}>Pay</Button>
          }
          renderExpanded={(line) => (
            <div className="mt-4 max-w-sm rounded-lg bg-slate-50 p-4">
              <PayForm
                outstanding={line.outstanding}
                submitLabel="Continue to payment"
                busyLabel="Opening payment page…"
                onCancel={() => setPayingId(null)}
                onSubmit={async (amount) => {
                  const session = await checkout.mutateAsync({
                    fee_assignment_id: line.id,
                    amount,
                  });
                  // Stripe's hosted page takes it from here. Nothing is
                  // recorded until the webhook arrives, so closing the tab at
                  // this point loses nothing and the payment still lands.
                  window.location.assign(session.checkout_url);
                }}
              />
              <p className="mt-3 text-xs text-slate-500">
                You will be taken to Stripe to pay by card. Test mode — no real money moves.
              </p>
            </div>
          )}
        />
      ) : null}
    </div>
  );
}
