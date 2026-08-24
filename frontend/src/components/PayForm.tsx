/**
 * "How much?" - shared by the bursar taking cash and the parent paying by card.
 *
 * The two do different things with the answer, so the action is a prop. What
 * they share is the validation, and sharing it is the point: the rules are the
 * API's, and having them written twice is how the two screens end up
 * disagreeing about whether 0.00 is a payment.
 *
 * Client-side validation here is a courtesy - it saves a round trip and puts
 * the message next to the box. It is not the check that matters. The server
 * validates again against a balance that may have moved since this page
 * loaded, and its answer is the one that decides; when it refuses, that
 * message is what gets shown.
 */

import { useState } from "react";

import { ApiError } from "../lib/api";
import { formatMoney, validateAmount } from "../lib/money";
import { Banner, Button, Field, Input } from "./ui";

export function PayForm({
  outstanding,
  submitLabel,
  busyLabel,
  onSubmit,
  onCancel,
}: {
  outstanding: string;
  submitLabel: string;
  busyLabel: string;
  onSubmit: (amount: string) => Promise<void>;
  onCancel?: () => void;
}) {
  const [amount, setAmount] = useState(outstanding);
  const [touched, setTouched] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Two errors, two places, never the same text twice: what the server said
  // goes in the banner, what is wrong with the box goes under the box.
  const localError = validateAmount(amount, outstanding);
  const fieldError = touched ? localError : null;

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setTouched(true);
    setServerError(null);
    if (localError) return;

    setBusy(true);
    try {
      await onSubmit(amount);
    } catch (caught) {
      // The balance may have moved while this form was open - a 409 saying so
      // is the most useful thing on the screen.
      setServerError(
        caught instanceof ApiError ? caught.message : "That did not go through. Try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      {serverError ? <Banner>{serverError}</Banner> : null}

      <Field
        label="Amount"
        error={fieldError ?? undefined}
        hint={`${formatMoney(outstanding)} still owed`}
      >
        <Input
          inputMode="decimal"
          name="amount"
          aria-label="Amount"
          value={amount}
          onChange={(event) => {
            setAmount(event.target.value);
            setServerError(null);
          }}
          onBlur={() => setTouched(true)}
          aria-invalid={fieldError || serverError ? true : undefined}
        />
      </Field>

      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={busy}>
          {busy ? busyLabel : submitLabel}
        </Button>
        <Button
          type="button"
          variant="secondary"
          onClick={() => setAmount(outstanding)}
          disabled={busy}
        >
          Pay it all
        </Button>
        {onCancel ? (
          <Button type="button" variant="ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
        ) : null}
      </div>
    </form>
  );
}
