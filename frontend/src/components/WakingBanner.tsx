/**
 * "The demo server is waking up."
 *
 * Free hosting spins the API down after fifteen quiet minutes and takes about
 * a minute to bring it back. The login page already explains that; this does
 * the same for every other screen, because the first visitor of the day does
 * not always arrive at the login page - a parent returning from Stripe lands
 * on the confirmation page, cold.
 *
 * It watches TanStack Query's in-flight count rather than the network: if
 * anything has been loading for longer than a normal request could take, say
 * why. It disappears the moment the requests do.
 */

import { useIsFetching, useIsMutating } from "@tanstack/react-query";
import { useEffect, useState } from "react";

const SLOW_AFTER_MS = 3000;

export function WakingBanner() {
  const busy = useIsFetching() + useIsMutating() > 0;
  // A fresh mount per busy episode: the timer starts when requests start and
  // is thrown away when they finish, with no state to reset by hand.
  return busy ? <SlowNotice /> : null;
}

function SlowNotice() {
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setSlow(true), SLOW_AFTER_MS);
    return () => clearTimeout(timer);
  }, []);

  if (!slow) return null;

  return (
    <div
      role="status"
      className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-center text-sm text-amber-900"
    >
      The demo server sleeps when nobody is using it. Waking it up — this can take up to a
      minute.
    </div>
  );
}
