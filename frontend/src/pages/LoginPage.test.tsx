import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthContext } from "../auth/context";
import { LoginPage } from "./LoginPage";
import { ApiError } from "../lib/api";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

function renderLogin(signIn: (email: string, password: string) => Promise<void>) {
  const auth = { user: null, isLoading: false, expired: false, signIn, signOut: () => {} };
  render(
    <QueryClientProvider client={new QueryClient()}>
      <AuthContext value={auth}>
        <MemoryRouter initialEntries={["/login"]}>
          <LoginPage />
        </MemoryRouter>
      </AuthContext>
    </QueryClientProvider>,
  );
}

async function fillAndSubmit(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Email"), "admin@sukuu.demo");
  await user.type(screen.getByLabelText("Password"), "sukuu-demo");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
afterEach(() => vi.useRealTimers());

describe("signing in", () => {
  it("shows the API's message when credentials are refused", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderLogin(vi.fn().mockRejectedValue(new ApiError(401, "Incorrect email or password")));

    await fillAndSubmit(user);

    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect email or password");
  });

  it("passes the rate limiter's message through verbatim", async () => {
    // "Try again in 12 minutes" tells the user to wait. Replacing it with a
    // generic failure tells them to keep guessing, which is the opposite.
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderLogin(
      vi.fn().mockRejectedValue(new ApiError(429, "Too many attempts. Try again in 12 minutes.")),
    );

    await fillAndSubmit(user);

    expect(await screen.findByRole("alert")).toHaveTextContent("Try again in 12 minutes");
  });
});

describe("the sleeping demo server", () => {
  it("says nothing while the request is merely normal", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderLogin(vi.fn().mockResolvedValue(undefined));

    await fillAndSubmit(user);

    expect(screen.queryByText(/sleeps when nobody/)).not.toBeInTheDocument();
  });

  it("explains itself once the wait gets long", async () => {
    // A free instance spins down after fifteen quiet minutes and takes about a
    // minute to wake. Unexplained, the first visitor of the day watches a
    // spinner and concludes it is broken.
    let release: () => void = () => {};
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderLogin(vi.fn().mockReturnValue(new Promise<void>((resolve) => (release = resolve))));

    await fillAndSubmit(user);
    await vi.advanceTimersByTimeAsync(3500);

    expect(await screen.findByText(/sleeps when nobody/)).toBeInTheDocument();

    release();
  });
});

describe("the demo logins", () => {
  it("fills the form when one is clicked, so nobody has to type them", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderLogin(vi.fn());

    await user.click(screen.getByRole("button", { name: "parent@sukuu.demo" }));

    expect(screen.getByLabelText("Email")).toHaveValue("parent@sukuu.demo");
    expect(screen.getByLabelText("Password")).toHaveValue("sukuu-demo");
  });
});
