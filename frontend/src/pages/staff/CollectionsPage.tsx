/**
 * The bursar's screen: who owes what, and taking money for it.
 *
 * Defaults to unpaid fees only, because that is the question being asked at a
 * desk with somebody standing in front of it. Everything else is a filter away.
 */

import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { PayForm } from "../../components/PayForm";
import {
  Amount,
  Badge,
  Banner,
  Button,
  Card,
  CardHeader,
  DataState,
  Pager,
  Select,
  Table,
  Td,
  Th,
} from "../../components/ui";
import { formatMoney } from "../../lib/money";
import { useAssignments, useClasses, useRecordCashPayment } from "../../lib/queries";
import type { FeeAssignment } from "../../lib/types";

const PAGE_SIZE = 25;

export function CollectionsPage() {
  // The class filter lives in the URL, not in component state. The dashboard
  // links straight to a class's collections, and with the filter held locally
  // that link navigated here and then showed everything - the worst kind of
  // broken, because it looks like it worked. It also makes a filtered view
  // something you can bookmark or send to a colleague.
  const [searchParams, setSearchParams] = useSearchParams();
  const classParam = searchParams.get("class_id");
  const classId = classParam ? Number(classParam) : undefined;

  const [outstandingOnly, setOutstandingOnly] = useState(true);
  const [offset, setOffset] = useState(0);
  const [payingId, setPayingId] = useState<number | null>(null);
  const [receipt, setReceipt] = useState<string | null>(null);

  function setClassId(next: number | undefined) {
    const params = new URLSearchParams(searchParams);
    if (next === undefined) params.delete("class_id");
    else params.set("class_id", String(next));
    // replace: filtering is not a step worth pressing Back through twice.
    setSearchParams(params, { replace: true });
  }

  const classes = useClasses({ limit: 100 });
  const { data, isPending, error } = useAssignments({
    class_id: classId,
    outstanding_only: outstandingOnly,
    limit: PAGE_SIZE,
    offset,
  });

  function resetTo(fn: () => void) {
    fn();
    setOffset(0);
    setPayingId(null);
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Collections</h1>
        <p className="mt-1 text-sm text-slate-500">Outstanding fees, and recording cash payments.</p>
      </div>

      {receipt ? <Banner tone="success">{receipt}</Banner> : null}

      <Card>
        <CardHeader
          title="Fees"
          subtitle={data ? `${data.total} matching` : undefined}
          actions={
            <>
              <Select
                aria-label="Filter by class"
                value={classId ?? ""}
                onChange={(event) =>
                  resetTo(() =>
                    setClassId(event.target.value ? Number(event.target.value) : undefined),
                  )
                }
              >
                <option value="">All classes</option>
                {classes.data?.items.map((schoolClass) => (
                  <option key={schoolClass.id} value={schoolClass.id}>
                    {schoolClass.name} · {schoolClass.academic_year}
                  </option>
                ))}
              </Select>
              <Select
                aria-label="Show"
                value={outstandingOnly ? "unpaid" : "all"}
                onChange={(event) => resetTo(() => setOutstandingOnly(event.target.value === "unpaid"))}
              >
                <option value="unpaid">Unpaid only</option>
                <option value="all">All fees</option>
              </Select>
            </>
          }
        />

        <DataState
          isPending={isPending}
          error={error}
          isEmpty={data?.items.length === 0}
          emptyMessage={
            outstandingOnly ? "Nothing outstanding. Everything here is paid." : "No fees match."
          }
        >
          <Table
            head={
              <tr>
                <Th>Student</Th>
                <Th>Fee</Th>
                <Th align="right">Owed</Th>
                <Th align="right">Action</Th>
              </tr>
            }
          >
            {data?.items.map((line) => (
              <Row
                key={line.id}
                line={line}
                isPaying={payingId === line.id}
                onPay={() => setPayingId(line.id)}
                onCancel={() => setPayingId(null)}
                onPaid={(message) => {
                  setPayingId(null);
                  setReceipt(message);
                }}
              />
            ))}
          </Table>
          <Pager
            total={data?.total ?? 0}
            limit={PAGE_SIZE}
            offset={offset}
            onChange={(next) => {
              setOffset(next);
              setPayingId(null);
            }}
          />
        </DataState>
      </Card>
    </div>
  );
}

function Row({
  line,
  isPaying,
  onPay,
  onCancel,
  onPaid,
}: {
  line: FeeAssignment;
  isPaying: boolean;
  onPay: () => void;
  onCancel: () => void;
  onPaid: (message: string) => void;
}) {
  const record = useRecordCashPayment();

  return (
    <>
      <tr className={isPaying ? "bg-slate-50" : undefined}>
        <Td>
          <span className="font-medium text-slate-900">{line.student.full_name}</span>
          <span className="ml-2 font-mono text-xs text-slate-400">
            {line.student.admission_number}
          </span>
        </Td>
        <Td>
          {line.fee_type.name}
          <span className="ml-2 text-slate-400">{line.period_label}</span>
        </Td>
        <Td align="right">
          {line.settled ? (
            <Badge tone="green">Paid</Badge>
          ) : (
            <span className="font-medium">
              <Amount value={line.outstanding} />
            </span>
          )}
        </Td>
        <Td align="right">
          {line.settled ? null : isPaying ? (
            <Button variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
          ) : (
            <Button variant="secondary" onClick={onPay}>
              Record cash
            </Button>
          )}
        </Td>
      </tr>

      {isPaying ? (
        <tr className="bg-slate-50">
          <td colSpan={4} className="px-5 pb-5">
            <div className="max-w-sm">
              <PayForm
                outstanding={line.outstanding}
                submitLabel="Record payment"
                busyLabel="Recording…"
                onCancel={onCancel}
                onSubmit={async (amount) => {
                  const result = await record.mutateAsync({
                    fee_assignment_id: line.id,
                    amount,
                  });
                  const after = result.fee_assignment;
                  onPaid(
                    `Recorded ${formatMoney(result.payment.amount_paid)} for ` +
                      `${line.student.full_name}. ` +
                      (after.settled
                        ? "That fee is now settled."
                        : `${formatMoney(after.outstanding)} still owed.`),
                  );
                }}
              />
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}
