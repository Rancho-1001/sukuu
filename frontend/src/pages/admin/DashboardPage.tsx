import { Link } from "react-router-dom";

import { Amount, Card, CardHeader, DataState, Table, Td, Th } from "../../components/ui";
import { useSchoolSummary } from "../../lib/queries";
import { toMinorUnits } from "../../lib/money";
import { Totals } from "../parent/MyChildrenPage";

export function DashboardPage() {
  const { data, isPending, error } = useSchoolSummary();

  // The class rows need not sum to the school totals: a student enrolled but
  // not yet placed is billed like anyone else and has no class row to sit in.
  // Surfacing the gap turns a number that looks wrong into a job to do.
  const classBilled = (data?.classes ?? []).reduce(
    (sum, row) => sum + (toMinorUnits(row.billed) ?? 0),
    0,
  );
  const unplaced = (toMinorUnits(data?.billed ?? "0.00") ?? 0) - classBilled;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Dashboard</h1>
        <p className="mt-1 text-sm text-slate-500">Collected and outstanding across the school.</p>
      </div>

      <DataState isPending={isPending} error={error}>
        {data ? (
          <div className="space-y-6">
            <Totals billed={data.billed} paid={data.paid} outstanding={data.outstanding} />

            <Card>
              <CardHeader
                title="By class"
                subtitle={
                  unplaced > 0
                    ? "Some fees belong to students who have not been placed in a class yet, so these rows do not add up to the totals above."
                    : undefined
                }
              />
              <DataState
                isPending={false}
                error={null}
                isEmpty={data.classes.length === 0}
                emptyMessage="No classes yet. Create one to get started."
              >
                <Table
                  head={
                    <tr>
                      <Th>Class</Th>
                      <Th align="right">Billed</Th>
                      <Th align="right">Paid</Th>
                      <Th align="right">Outstanding</Th>
                    </tr>
                  }
                >
                  {data.classes.map((row) => (
                    <tr key={row.school_class.id}>
                      <Td>
                        <Link
                          to={`/collections?class_id=${row.school_class.id}`}
                          className="font-medium text-slate-900 hover:text-indigo-600"
                        >
                          {row.school_class.name}
                        </Link>
                        <span className="ml-2 text-slate-400">{row.school_class.academic_year}</span>
                      </Td>
                      <Td align="right">
                        <Amount value={row.billed} />
                      </Td>
                      <Td align="right" className="text-emerald-700">
                        <Amount value={row.paid} />
                      </Td>
                      <Td align="right" className="font-medium">
                        <Amount value={row.outstanding} />
                      </Td>
                    </tr>
                  ))}
                </Table>
              </DataState>
            </Card>
          </div>
        ) : null}
      </DataState>
    </div>
  );
}
