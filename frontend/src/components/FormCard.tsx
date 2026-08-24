/**
 * A card with a form that is closed until it is wanted.
 *
 * Every admin screen is a list plus "add one", and an always-open form pushes
 * the list - the thing people came for - below the fold.
 */

import { useState } from "react";
import type { ReactNode } from "react";

import { ApiError } from "../lib/api";
import { Banner, Button, Card, CardHeader } from "./ui";

export function FormCard({
  title,
  subtitle,
  openLabel,
  submitLabel,
  onSubmit,
  children,
  successMessage,
}: {
  title: string;
  subtitle?: string;
  openLabel: string;
  submitLabel: string;
  onSubmit: (form: FormData) => Promise<string | void>;
  children: (error: ApiError | null) => ReactNode;
  successMessage?: string;
}) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // Held onto before the await. React clears `currentTarget` once the
    // handler returns, so reaching for it afterwards throws - and throwing
    // there lands in the catch below, which is how a successful save ends up
    // showing an error banner underneath its own success message.
    const element = event.currentTarget;
    const form = new FormData(element);
    setError(null);
    setMessage(null);
    setBusy(true);
    try {
      const result = await onSubmit(form);
      setMessage(typeof result === "string" ? result : (successMessage ?? "Saved."));
      element.reset();
    } catch (caught) {
      // The API's envelope carries both a sentence and the fields it blamed,
      // so the banner and the inputs can each say their part.
      setError(
        caught instanceof ApiError ? caught : new ApiError(0, "Something went wrong. Try again."),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title={title}
        subtitle={subtitle}
        actions={
          <Button variant={open ? "ghost" : "secondary"} onClick={() => setOpen(!open)}>
            {open ? "Close" : openLabel}
          </Button>
        }
      />
      {message ? (
        <div className="px-5 pt-4">
          <Banner tone="success">{message}</Banner>
        </div>
      ) : null}
      {open ? (
        <form onSubmit={handleSubmit} className="space-y-4 px-5 py-5">
          {error ? <Banner>{error.message}</Banner> : null}
          <div className="grid gap-4 sm:grid-cols-2">{children(error)}</div>
          <Button type="submit" disabled={busy}>
            {busy ? "Saving…" : submitLabel}
          </Button>
        </form>
      ) : null}
    </Card>
  );
}
