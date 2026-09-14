import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WakingBanner } from "./WakingBanner";

/** A query that resolves only when the test says so. */
function Slow({ release }: { release: { current: () => void } }) {
  useQuery({
    queryKey: ["slow"],
    queryFn: () => new Promise<string>((resolve) => (release.current = () => resolve("done"))),
  });
  return null;
}

function setup() {
  const release = { current: () => {} };
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <WakingBanner />
      <Slow release={release} />
    </QueryClientProvider>,
  );
  // Let the query actually start and the banner mount, so its timer is armed
  // before the clock moves. Effects flush at the end of act, after any
  // advance made inside it.
  act(() => vi.advanceTimersByTime(10));
  return release;
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("WakingBanner", () => {
  it("says nothing while a request is merely in flight", () => {
    setup();
    act(() => vi.advanceTimersByTime(1000));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("explains the wait once a request has hung for a few seconds", () => {
    setup();
    act(() => vi.advanceTimersByTime(3500));
    expect(screen.getByRole("status")).toHaveTextContent(/sleeps when nobody/);
  });

  it("disappears the moment the request completes", async () => {
    const release = setup();
    act(() => vi.advanceTimersByTime(3500));
    expect(screen.getByRole("status")).toBeInTheDocument();

    await act(async () => {
      release.current();
      // The resolution passes through several awaits inside TanStack before it
      // notifies, and the notification itself is batched through a timer.
      await vi.advanceTimersByTimeAsync(50);
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
