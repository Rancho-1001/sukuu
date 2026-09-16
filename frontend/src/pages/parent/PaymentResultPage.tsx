/**
 * Where the payment processor sends a parent after checkout.
 *
 * The redirect is not proof of payment - only the webhook is, and it arrives
 * on its own schedule. So the success page does not say "paid". It says
 * "confirming", watches the balance, and says "confirmed" only when the
 * amount paid has moved past what it was when checkout started. That number
 * (`paid_before`) rides on the URL because nothing else survives the round
 * trip through the processor.
 *
 * If the webhook is slow - the API was asleep, the processor is retrying - the page
 * says that too, rather than spinning forever or lying.
 */

import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Amount, Banner, Button, Card, Spinner } from "../../components/ui";
import { toMinorUnits } from "../../lib/money";
import { useGateway, useStudentBalance } from "../../lib/queries";

const POLL_MS = 3000;
const GIVE_UP_AFTER_MS = 90_000;

function useReturnContext() {
  const [params] = useSearchParams();
  const student = Number(params.get("student"));
  const fee = Number(params.get("fee"));
  const paidBefore = params.get("paid_before") ?? "";
  const valid = Number.isFinite(student) && student > 0 && Number.isFinite(fee) && fee > 0;
  return { student, fee, paidBefore, valid };
}

export function PaymentSuccessPage() {
  const { student, fee, paidBefore, valid } = useReturnContext();
  const [waitedTooLong, setWaitedTooLong] = useState(false);
  // Named honestly or not at all: "Stripe" on a Paystack deployment would be
  // a page telling a parent something false about their own money.
  const processor = useGateway().data?.display_name ?? "The payment provider";

  const { data: balance } = useStudentBalance(valid ? student : undefined, {
    // Keep asking until the payment shows up or we give up waiting.
    refetchInterval: (query) => {
      const line = query.state.data?.lines.find((item) => item.id === fee);
      const landed =
        line !== undefined &&
        (toMinorUnits(line.amount_paid) ?? 0) > (toMinorUnits(paidBefore) ?? 0);
      return landed || waitedTooLong ? false : POLL_MS;
    },
  });

  useEffect(() => {
    const timer = setTimeout(() => setWaitedTooLong(true), GIVE_UP_AFTER_MS);
    return () => clearTimeout(timer);
  }, []);

  const line = balance?.lines.find((item) => item.id === fee);
  const paidNow = line ? (toMinorUnits(line.amount_paid) ?? 0) : null;
  const landed = paidNow !== null && paidNow > (toMinorUnits(paidBefore) ?? 0);
  const backTo = valid ? `/my-children/${student}` : "/my-children";

  return (
    <div className="mx-auto max-w-lg space-y-6 py-8">
      <Card className="p-8 text-center">
        {!valid ? (
          <>
            <h1 className="text-2xl font-semibold text-slate-900">Thank you</h1>
            <p className="mt-2 text-slate-600">
              Your payment is being confirmed. It will appear in your child's history shortly.
            </p>
          </>
        ) : landed && line ? (
          <>
            <div
              aria-hidden
              className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-emerald-100 text-2xl text-emerald-700"
            >
              ✓
            </div>
            <h1 className="text-2xl font-semibold text-slate-900">Payment confirmed</h1>
            <p className="mt-2 text-slate-600">
              {balance?.student.full_name} · {line.fee_type.name} · {line.period_label}
            </p>
            <p className="mt-4 text-3xl font-semibold text-emerald-700">
              <Amount value={line.amount_paid} />
              <span className="ml-2 text-base font-normal text-slate-500">
                of <Amount value={line.amount} /> paid
              </span>
            </p>
            {line.settled ? (
              <p className="mt-2 text-sm text-emerald-700">This fee is now settled.</p>
            ) : (
              <p className="mt-2 text-sm text-slate-500">
                <Amount value={line.outstanding} /> still owed on this fee.
              </p>
            )}
          </>
        ) : waitedTooLong ? (
          <>
            <h1 className="text-2xl font-semibold text-slate-900">Still confirming</h1>
            <div className="mt-4 text-left">
              <Banner tone="info">
                {processor} accepted the payment, but the confirmation has not reached the school
                yet. This usually means the demo server was asleep — {processor} will retry on its
                own, and the payment will appear in the history without you doing anything.
              </Banner>
            </div>
          </>
        ) : (
          <>
            <h1 className="text-2xl font-semibold text-slate-900">Confirming your payment</h1>
            <p className="mt-2 text-slate-600">
              {processor} has taken the payment. Waiting for the school's records to update — this
              takes a few seconds.
            </p>
            <div className="mt-6">
              <Spinner label="Confirming with the bank" />
            </div>
          </>
        )}

        <div className="mt-8">
          <Link to={backTo}>
            <Button variant={landed ? "primary" : "secondary"}>
              {valid ? "Back to fees" : "My children"}
            </Button>
          </Link>
        </div>
      </Card>

      <p className="text-center text-xs text-slate-500">
        Test mode — no real money moved.
      </p>
    </div>
  );
}

export function PaymentCancelledPage() {
  const { student, valid } = useReturnContext();
  const backTo = valid ? `/my-children/${student}` : "/my-children";

  return (
    <div className="mx-auto max-w-lg py-8">
      <Card className="p-8 text-center">
        <h1 className="text-2xl font-semibold text-slate-900">Payment cancelled</h1>
        <p className="mt-2 text-slate-600">
          No payment was taken and nothing has changed. You can pay whenever you're ready.
        </p>
        <div className="mt-8">
          <Link to={backTo}>
            <Button>Back to fees</Button>
          </Link>
        </div>
      </Card>
    </div>
  );
}
