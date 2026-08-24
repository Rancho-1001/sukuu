import type { UserRole } from "../lib/types";

/** Where each role starts, and where a wrong turn sends them back to. */
export function homeFor(role: UserRole): string {
  if (role === "admin") return "/dashboard";
  if (role === "staff") return "/collections";
  return "/my-children";
}
