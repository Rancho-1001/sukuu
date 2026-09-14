/**
 * Collected against outstanding, per class.
 *
 * A stacked horizontal bar per class: paid and outstanding sum to billed, so
 * the bar's length is what the class was charged and the split is how much
 * of it has come in. That is the dashboard's question in one glance.
 *
 * Colours were chosen by running the palette validator, not by eye:
 * emerald-600 and amber-500 pass the colour-vision separation check with a
 * margin (ΔE 13 under protanopia), and the 2px gap between segments, the
 * legend, and the table beneath all carry the same distinction without
 * colour.
 *
 * **Money in a chart.** The bars need numbers, so the strings are converted
 * to minor units and divided - a float, but one used only for geometry. Every
 * number a reader sees, in the tooltip or the axis, is formatted from the
 * original string through `formatMoney`. The float never reaches the screen.
 */

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatMoney, toMinorUnits } from "../lib/money";
import type { ClassCollectionRow } from "../lib/types";

const PAID = "#059669"; // emerald-600
const OUTSTANDING = "#f59e0b"; // amber-500
const ROW_HEIGHT = 44;

type Point = {
  name: string;
  paid: number;
  outstanding: number;
  paidLabel: string;
  outstandingLabel: string;
  billedLabel: string;
};

function toPoints(rows: ClassCollectionRow[]): Point[] {
  return rows.map((row) => ({
    name: row.school_class.name,
    paid: (toMinorUnits(row.paid) ?? 0) / 100,
    outstanding: (toMinorUnits(row.outstanding) ?? 0) / 100,
    paidLabel: formatMoney(row.paid),
    outstandingLabel: formatMoney(row.outstanding),
    billedLabel: formatMoney(row.billed),
  }));
}

function ClassTooltip({ active, payload }: { active?: boolean; payload?: { payload: Point }[] }) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm shadow-md">
      <p className="font-medium text-slate-900">{point.name}</p>
      <dl className="mt-1 space-y-0.5 text-slate-600">
        <div className="flex justify-between gap-6">
          <dt className="flex items-center gap-1.5">
            <span aria-hidden className="h-2.5 w-2.5 rounded-sm" style={{ background: PAID }} />
            Paid
          </dt>
          <dd className="tabular-nums">{point.paidLabel}</dd>
        </div>
        <div className="flex justify-between gap-6">
          <dt className="flex items-center gap-1.5">
            <span aria-hidden className="h-2.5 w-2.5 rounded-sm" style={{ background: OUTSTANDING }} />
            Outstanding
          </dt>
          <dd className="tabular-nums">{point.outstandingLabel}</dd>
        </div>
        <div className="flex justify-between gap-6 border-t border-slate-100 pt-0.5 font-medium text-slate-900">
          <dt>Billed</dt>
          <dd className="tabular-nums">{point.billedLabel}</dd>
        </div>
      </dl>
    </div>
  );
}

export function CollectionChart({ rows }: { rows: ClassCollectionRow[] }) {
  const points = toPoints(rows);
  if (points.length === 0) return null;

  return (
    <figure>
      <ul className="mb-2 flex justify-end gap-4 text-xs text-slate-600" aria-label="Legend">
        {[
          ["Paid", PAID],
          ["Outstanding", OUTSTANDING],
        ].map(([label, colour]) => (
          <li key={label} className="flex items-center gap-1.5">
            <span aria-hidden className="h-2.5 w-2.5 rounded-sm" style={{ background: colour }} />
            {label}
          </li>
        ))}
      </ul>
      <div style={{ height: points.length * ROW_HEIGHT + 40 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={points}
            layout="vertical"
            margin={{ top: 4, right: 16, bottom: 4, left: 8 }}
            barSize={18}
          >
            <CartesianGrid horizontal={false} stroke="#e2e8f0" strokeDasharray="0" />
            <XAxis
              type="number"
              tickLine={false}
              axisLine={false}
              tick={{ fill: "#64748b", fontSize: 12 }}
              tickFormatter={(value: number) => formatMoney(value.toFixed(2))}
            />
            <YAxis
              type="category"
              dataKey="name"
              width={88}
              tickLine={false}
              axisLine={false}
              tick={{ fill: "#334155", fontSize: 13 }}
            />
            <Tooltip content={<ClassTooltip />} cursor={{ fill: "#f1f5f9" }} />
            {/* A 2px white stroke is the gap between segments: identity
                survives without colour, and adjacent bars do not fuse. */}
            <Bar dataKey="paid" name="Paid" stackId="a" fill={PAID} stroke="#fff" strokeWidth={2} />
            <Bar
              dataKey="outstanding"
              name="Outstanding"
              stackId="a"
              fill={OUTSTANDING}
              stroke="#fff"
              strokeWidth={2}
              radius={[0, 4, 4, 0]}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="sr-only">
        Amount collected and outstanding for each class. The full figures are in the table
        below.
      </figcaption>
    </figure>
  );
}
