/**
 * Money, in one place.
 *
 * The API sends amounts as strings - `"250.00"`, quoted - because a JSON
 * number becomes an IEEE 754 double the moment JavaScript parses it, and that
 * is the same binary float the database refuses to store. Nothing in this file
 * does arithmetic on those strings, and nothing outside this file formats
 * them. That is the whole discipline: `Number("250.00") * 1.1` is a bug that
 * looks like code, and the only way to keep it out is to have one door.
 *
 * Comparison is fine on integer minor units, which is what `toMinorUnits`
 * exists for - the payment form has to know whether 60.00 is more than the
 * 55.00 still owed, and that question is asked in cents, not in floats.
 */

const CURRENCY = import.meta.env.VITE_CURRENCY ?? "USD";

const formatter = new Intl.NumberFormat(undefined, {
  style: "currency",
  currency: CURRENCY,
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** `"250.00"` -> `"$250.00"`. The only function that renders an amount. */
export function formatMoney(amount: string): string {
  const minor = toMinorUnits(amount);
  if (minor === null) return formatter.format(0);
  // Intl needs a number, and this is the one place it is safe: minor units are
  // integers, and no school's ledger comes close to 2^53 cents.
  return formatter.format(minor / 100);
}

/**
 * `"250.00"` -> `25000`, or null if it is not an amount.
 *
 * Integer cents, so two amounts can be compared and subtracted without a float
 * ever being involved.
 */
export function toMinorUnits(amount: string): number | null {
  const trimmed = amount.trim();
  if (!/^-?\d+(\.\d{1,2})?$/.test(trimmed)) return null;

  const negative = trimmed.startsWith("-");
  const [whole, fraction = ""] = trimmed.replace("-", "").split(".");
  const cents = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  return negative ? -cents : cents;
}

/** `25000` -> `"250.00"`, the shape the API expects back. */
export function fromMinorUnits(minor: number): string {
  const sign = minor < 0 ? "-" : "";
  const absolute = Math.abs(Math.trunc(minor));
  return `${sign}${Math.floor(absolute / 100)}.${String(absolute % 100).padStart(2, "0")}`;
}

/**
 * What is wrong with an amount someone typed, or null if nothing is.
 *
 * Mirrors the rules the API enforces so the payer is told before a round trip,
 * not instead of one: the server checks all of this again, and it is the
 * server's answer that decides.
 */
export function validateAmount(raw: string, maximumOwed: string): string | null {
  if (raw.trim() === "") return "Enter an amount.";

  const minor = toMinorUnits(raw);
  if (minor === null) return "Enter an amount like 25.00.";
  if (minor <= 0) return "The amount must be more than zero.";

  const limit = toMinorUnits(maximumOwed);
  if (limit !== null && minor > limit) {
    return `That is more than the ${formatMoney(maximumOwed)} still owed.`;
  }
  return null;
}
