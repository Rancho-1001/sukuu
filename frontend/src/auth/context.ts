/**
 * The auth context and its hook, with no components in the file.
 *
 * Split from the provider so that editing either one still hot-reloads: React
 * Fast Refresh gives up on a module that exports both a component and
 * something else.
 */

import { createContext, useContext } from "react";

import type { User } from "../lib/types";

export interface AuthValue {
  user: User | null;
  /** True until the stored token has been checked, so guards do not act early. */
  isLoading: boolean;
  /** Set when a session ended by itself rather than by clicking sign out. */
  expired: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => void;
}

export const AuthContext = createContext<AuthValue | null>(null);

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside an AuthProvider");
  return value;
}
