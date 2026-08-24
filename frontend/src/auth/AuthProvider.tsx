/**
 * Who is signed in.
 *
 * The token is the only thing persisted. The user behind it is re-fetched from
 * `/auth/me` on every load rather than stored alongside it, so a role change -
 * or a deleted account - takes effect on the next page load instead of
 * whenever the browser happens to forget.
 *
 * Nothing here is a security control. The API decides what each role may do
 * and answers 403 or 404 regardless of what this file believes; every guard
 * built on top of it is there so people are not shown doors that will not
 * open.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { api, readToken, setSessionExpiredHandler, writeToken } from "../lib/api";
import type { User } from "../lib/types";
import { AuthContext } from "./context";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  // Initialised from storage rather than set inside an effect: with no token
  // there is nothing to wait for, and starting at true would render a spinner
  // for one frame and then immediately re-render without it.
  const [isLoading, setIsLoading] = useState(() => readToken() !== null);
  const [expired, setExpired] = useState(false);
  const queryClient = useQueryClient();

  const clear = useCallback(() => {
    writeToken(null);
    setUser(null);
    // Otherwise the next person to sign in on this browser sees the previous
    // one's students for a frame before the refetch lands.
    queryClient.clear();
  }, [queryClient]);

  useEffect(() => {
    setSessionExpiredHandler(() => {
      setExpired(true);
      clear();
    });
  }, [clear]);

  useEffect(() => {
    if (!readToken()) return;

    let cancelled = false;
    api
      .get<User>("/auth/me")
      .then((me) => {
        if (!cancelled) setUser(me);
      })
      .catch(() => {
        // A stored token that no longer works. The 401 handler has already
        // cleared it; there is nothing to show the user, who never asked.
        if (!cancelled) setUser(null);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const token = await api.login(email, password);
    writeToken(token.access_token);
    setExpired(false);
    const me = await api.get<User>("/auth/me");
    setUser(me);
  }, []);

  const signOut = useCallback(() => {
    setExpired(false);
    clear();
  }, [clear]);

  const value = useMemo(
    () => ({ user, isLoading, expired, signIn, signOut }),
    [user, isLoading, expired, signIn, signOut],
  );

  return <AuthContext value={value}>{children}</AuthContext>;
}
