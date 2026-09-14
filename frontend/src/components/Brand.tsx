/**
 * The mark: three ledger lines, the last one short.
 *
 * A ledger where the last entry is still open is what a fee balance is. It
 * reads at 16px in a browser tab and at 40px in a header, which is the whole
 * brief for a mark.
 */

import { Link } from "react-router-dom";

export function BrandMark({ size = 28 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      aria-hidden
      className="shrink-0"
    >
      <rect width="32" height="32" rx="8" fill="#4f46e5" />
      <rect x="8" y="9" width="16" height="4" rx="2" fill="#fff" />
      <rect x="8" y="15" width="16" height="4" rx="2" fill="#fff" opacity=".85" />
      <rect x="8" y="21" width="10" height="4" rx="2" fill="#fff" opacity=".7" />
    </svg>
  );
}

export function Brand({ to = "/" }: { to?: string }) {
  return (
    <Link to={to} className="flex items-center gap-2.5" aria-label="Sukuu home">
      <BrandMark />
      <span className="text-lg font-semibold tracking-tight text-slate-900">Sukuu</span>
    </Link>
  );
}
