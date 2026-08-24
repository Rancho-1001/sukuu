/**
 * Route guards.
 *
 * These decide what is *shown*, never what is *allowed*. The API enforces both
 * the role boundaries and the per-row ones - a parent asking for another
 * family's child gets a 404 whatever this file does - so nothing here is load
 * bearing for security. Hiding a door that would not open is courtesy.
 */

import { Navigate, Outlet, useLocation } from "react-router-dom";

import { Spinner } from "../components/ui";
import { useAuth } from "./context";
import { homeFor } from "./roles";
import type { UserRole } from "../lib/types";

function Waiting() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <Spinner label="Signing you in" />
    </div>
  );
}

export function RequireAuth() {
  const { user, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) return <Waiting />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <Outlet />;
}

export function RequireRole({ roles }: { roles: UserRole[] }) {
  const { user, isLoading } = useAuth();

  if (isLoading) return <Waiting />;
  if (!user) return <Navigate to="/login" replace />;
  // Send them somewhere they can actually work rather than showing a wall.
  if (!roles.includes(user.role)) return <Navigate to={homeFor(user.role)} replace />;
  return <Outlet />;
}

