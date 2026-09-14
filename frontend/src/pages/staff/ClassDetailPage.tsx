/**
 * One class's collection position: the totals, and who in it owes what.
 *
 * The rows are paginated and the totals are not, on purpose - the totals
 * cover the whole class. A figure that only added up the current page would
 * shrink when someone clicked "next", and a dashboard states such numbers
 * with complete confidence.
 */

import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Totals } from "../../components/StudentLedger";
import { Amount, Badge, Card, CardHeader, DataState, Pager, Table, Td, Th } from "../../components/ui";
import { useClassBalance } from "../../lib/queries";

const PAGE_SIZE = 25;

export function ClassDetailPage() {
  const { classId } = useParams();
  const id = Number(classId);
  const valid = Number.isFinite(id) && id > 0;
  const [offset, setOffset] = useState(0);
  const { data, isPending, error } = useClassBalance(valid ? id : undefined, offset);

  return (
    <div className="space-y-6">
      <div>
        <Link to="/dashboard" className="text-sm text-indigo-600 hover:underline">
          ← Dashboard
        </Link>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">
          {data?.school_class.name ?? "Class"}
        </h1>
        {data ? (
          <p className="mt-1 text-sm text-slate-500">
            {data.school_class.academic_year} ·{" "}
            <Link to={`/collections?class_id=${id}`} className="text-indigo-600 hover:underline">
              Record payments for this class →
            </Link>
          </p>
        ) : null}
      </div>

      <DataState isPending={isPending} error={error}>
        {data ? (
          <div className="space-y-6">
            <Totals billed={data.billed} paid={data.paid} outstanding={data.outstanding} />

            <Card>
              <CardHeader title="Students" subtitle={`${data.students.total} in this class`} />
              <DataState
                isPending={false}
                error={null}
                isEmpty={data.students.items.length === 0}
                emptyMessage="Nobody is in this class yet."
              >
                <Table
                  head={
                    <tr>
                      <Th>Student</Th>
                      <Th align="right">Billed</Th>
                      <Th align="right">Paid</Th>
                      <Th align="right">Outstanding</Th>
                    </tr>
                  }
                >
                  {data.students.items.map((row) => (
                    <tr key={row.student.id}>
                      <Td label="Student">
                        <Link
                          to={`/students/${row.student.id}`}
                          className="font-medium text-slate-900 hover:text-indigo-600"
                        >
                          {row.student.full_name}
                        </Link>
                        <span className="ml-2 font-mono text-xs text-slate-400">
                          {row.student.admission_number}
                        </span>
                      </Td>
                      <Td label="Billed" align="right">
                        <Amount value={row.billed} />
                      </Td>
                      <Td label="Paid" align="right" className="text-emerald-700">
                        <Amount value={row.paid} />
                      </Td>
                      <Td label="Outstanding" align="right">
                        {row.outstanding === "0.00" ? (
                          <Badge tone="green">Settled</Badge>
                        ) : (
                          <span className="font-medium">
                            <Amount value={row.outstanding} />
                          </span>
                        )}
                      </Td>
                    </tr>
                  ))}
                </Table>
                <Pager
                  total={data.students.total}
                  limit={PAGE_SIZE}
                  offset={offset}
                  onChange={setOffset}
                />
              </DataState>
            </Card>
          </div>
        ) : null}
      </DataState>
    </div>
  );
}
