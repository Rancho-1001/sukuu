/** A payment method as a bursar reads it: the words from `lib/methods`, cash in amber. */

import { methodLabel } from "../lib/methods";
import type { PaymentMethod } from "../lib/types";
import { Badge } from "./ui";

export function MethodBadge({ method }: { method: PaymentMethod }) {
  return <Badge tone={method === "cash" ? "amber" : "slate"}>{methodLabel(method)}</Badge>;
}
