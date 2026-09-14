import { NavLink, Outlet } from "react-router-dom";

import { useAuth } from "../auth/context";
import { Brand } from "./Brand";
import { Button } from "./ui";
import { WakingBanner } from "./WakingBanner";
import type { UserRole } from "../lib/types";

/**
 * Navigation per role.
 *
 * The lists differ because the jobs differ, not because the links are a
 * permission: a parent who types /students still gets a 403 from the API, and
 * the route guard sends them home before that. This is signposting.
 */
const NAV: Record<UserRole, { to: string; label: string }[]> = {
  admin: [
    { to: "/dashboard", label: "Dashboard" },
    { to: "/students", label: "Students" },
    { to: "/classes", label: "Classes" },
    { to: "/fee-types", label: "Fee types" },
    { to: "/assignments", label: "Fees" },
    { to: "/collections", label: "Collections" },
    { to: "/payments", label: "Payments" },
  ],
  staff: [
    { to: "/collections", label: "Collections" },
    { to: "/payments", label: "Payments" },
    { to: "/students", label: "Students" },
  ],
  parent: [{ to: "/my-children", label: "My children" }],
};

const ROLE_LABEL: Record<UserRole, string> = {
  admin: "Administrator",
  staff: "Bursar",
  parent: "Parent",
};

export function Layout() {
  const { user, signOut } = useAuth();
  if (!user) return null;

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-2.5">
          <Brand />

          {/* One row that scrolls sideways on a phone rather than wrapping
              into a second line and pushing the page down. */}
          <nav
            aria-label="Main"
            className="-mx-1 flex flex-1 gap-1 overflow-x-auto px-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
          >
            {NAV[user.role].map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `shrink-0 rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                    isActive ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-slate-100"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="flex shrink-0 items-center gap-3">
            <span className="hidden text-right text-sm leading-tight sm:block">
              <span className="block font-medium text-slate-800">{user.name}</span>
              <span className="block text-xs text-slate-500">{ROLE_LABEL[user.role]}</span>
            </span>
            <Button variant="secondary" onClick={signOut}>
              Sign out
            </Button>
          </div>
        </div>
      </header>

      <WakingBanner />

      <main className="mx-auto max-w-6xl px-4 py-8">
        <Outlet />
      </main>

      <footer className="mx-auto max-w-6xl px-4 pb-8 pt-4 text-xs text-slate-400">
        Sukuu is a portfolio project. Demo data; Stripe in test mode; no real money moves.
      </footer>
    </div>
  );
}
