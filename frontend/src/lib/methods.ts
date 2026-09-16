/**
 * Payment methods as a bursar reads them. One place for the words, so a new
 * channel is added here and nowhere else.
 */

import type { PaymentMethod } from "./types";

export const METHOD_LABELS: Record<PaymentMethod, string> = {
  cash: "Cash",
  card: "Card",
  mobile_money: "Mobile money",
  bank: "Bank",
};

/** Every method, in the order a filter should list them. */
export const ALL_METHODS = Object.keys(METHOD_LABELS) as PaymentMethod[];

export function methodLabel(method: PaymentMethod): string {
  return METHOD_LABELS[method] ?? method;
}

/** "mobile money, card or bank" - for a sentence about what a gateway takes. */
export function describeMethods(methods: PaymentMethod[]): string {
  const words = methods.map((m) => methodLabel(m).toLowerCase());
  if (words.length <= 1) return words[0] ?? "";
  return `${words.slice(0, -1).join(", ")} or ${words[words.length - 1]}`;
}
