/**
 * Rendering a page the way the app does: query client, router, and a signed-in
 * user.
 *
 * `route` is what makes URL-driven state testable - a filter held in the
 * address bar is only correct if arriving at the address applies it.
 *
 * The auth value is supplied directly rather than by mounting the real
 * provider, which would fetch `/auth/me` and make every page test depend on
 * the shape of a request it does not care about.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";

import { AuthContext } from "../auth/context";
import type { User, UserRole } from "../lib/types";

function userWithRole(role: UserRole): User {
  return { id: 1, email: `${role}@sukuu.demo`, name: `Test ${role}`, role };
}

export function renderWithProviders(
  ui: ReactElement,
  { route = "/", role = "admin" as UserRole }: { route?: string; role?: UserRole } = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });

  const auth = {
    user: userWithRole(role),
    isLoading: false,
    expired: false,
    signIn: async () => {},
    signOut: () => {},
  };

  return render(
    <QueryClientProvider client={queryClient}>
      <AuthContext value={auth}>
        <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
      </AuthContext>
    </QueryClientProvider>,
  );
}

/** Every URL the page asked for, in order. */
export function requestedUrls(fetchMock: { mock: { calls: unknown[][] } }): string[] {
  return fetchMock.mock.calls.map((call) => String(call[0]));
}
