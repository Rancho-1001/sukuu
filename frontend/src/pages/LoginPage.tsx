import { useEffect, useRef, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/context";
import { homeFor } from "../auth/roles";
import { Banner, Button, Field, Input } from "../components/ui";
import { ApiError } from "../lib/api";

const DEMO_LOGINS = [
  { role: "Admin", email: "admin@sukuu.demo" },
  { role: "Bursar", email: "bursar@sukuu.demo" },
  { role: "Parent", email: "parent@sukuu.demo" },
];

export function LoginPage() {
  const { user, signIn, expired } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // The demo API sleeps after fifteen quiet minutes and takes about a minute to
  // wake. Without a word about it, the first visitor of the day watches a
  // spinner and concludes the thing is broken.
  const [slow, setSlow] = useState(false);
  const slowTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (slowTimer.current) clearTimeout(slowTimer.current);
  }, []);

  if (user) return <Navigate to={homeFor(user.role)} replace />;

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    slowTimer.current = setTimeout(() => setSlow(true), 3000);
    try {
      await signIn(email, password);
      const from = (location.state as { from?: string } | null)?.from;
      navigate(from ?? "/", { replace: true });
    } catch (caught) {
      // The API deliberately does not say which half was wrong, and neither
      // does this. Its rate limiter also answers here, and that message is
      // worth showing verbatim - it tells the user to wait rather than to
      // keep guessing.
      setError(caught instanceof ApiError ? caught.message : "Could not sign in. Try again.");
    } finally {
      if (slowTimer.current) clearTimeout(slowTimer.current);
      setSlow(false);
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Sukuu</h1>
          <p className="mt-1 text-sm text-slate-500">School fee management</p>
        </div>

        <form onSubmit={onSubmit} className="space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          {expired ? <Banner tone="info">Your session ended. Please sign in again.</Banner> : null}
          {error ? <Banner>{error}</Banner> : null}

          <Field label="Email">
            <Input
              type="email"
              name="email"
              autoComplete="username"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </Field>

          <Field label="Password">
            <Input
              type="password"
              name="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </Field>

          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </Button>

          {slow ? (
            <p role="status" className="text-center text-sm text-slate-500">
              The demo server sleeps when nobody is using it. Waking it up — this can
              take up to a minute.
            </p>
          ) : null}
        </form>

        <div className="mt-6 rounded-lg border border-slate-200 bg-white/60 p-4 text-sm">
          <p className="mb-2 font-medium text-slate-700">Demo logins</p>
          <ul className="space-y-1 text-slate-600">
            {DEMO_LOGINS.map((login) => (
              <li key={login.email} className="flex items-center justify-between gap-3">
                <span>{login.role}</span>
                <button
                  type="button"
                  className="font-mono text-xs text-indigo-600 hover:underline"
                  onClick={() => {
                    setEmail(login.email);
                    setPassword("sukuu-demo");
                  }}
                >
                  {login.email}
                </button>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-slate-500">
            Password <span className="font-mono">sukuu-demo</span> for all three.
          </p>
        </div>
      </div>
    </div>
  );
}
