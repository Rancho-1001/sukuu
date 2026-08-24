import { NavLink, Outlet } from "react-router-dom";

import { useAuth } from "../auth/context";
import { Button } from "./ui";
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
  ],
  staff: [
    { to: "/collections", label: "Collections" },
    { to: "/students", label: "Students" },
  ],
  parent: [{ to: "/my-children", label: "My children" }],
};

export function Layout() {
  const { user, signOut } = useAuth();
  if (!user) return null;

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3">
          <span className="text-lg font-semibold tracking-tight text-slate-900">Sukuu</span>

          <nav className="flex flex-1 flex-wrap gap-1">
            {NAV[user.role].map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                    isActive ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-slate-100"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="flex items-center gap-3">
            <span className="hidden text-sm text-slate-500 sm:inline">
              {user.name} · <span className="capitalize">{user.role}</span>
            </span>
            <Button variant="secondary" onClick={signOut}>
              Sign out
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  );
}
