import { Link } from "react-router-dom";

import { Badge, Card, DataState } from "../../components/ui";
import { useMyChildren } from "../../lib/queries";
import type { Student } from "../../lib/types";

export function MyChildrenPage() {
  const { data: children, isPending, error } = useMyChildren();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">My children</h1>
        <p className="mt-1 text-sm text-slate-500">Fees, payments, and what is still owed.</p>
      </div>

      <Card>
        <DataState
          isPending={isPending}
          error={error}
          isEmpty={children?.length === 0}
          emptyMessage="No children are linked to your account yet. The school office can attach them."
        >
          <ul className="divide-y divide-slate-100">
            {children?.map((child) => (
              <ChildRow key={child.id} child={child} />
            ))}
          </ul>
        </DataState>
      </Card>
    </div>
  );
}

function ChildRow({ child }: { child: Student }) {
  return (
    <li>
      <Link
        to={`/my-children/${child.id}`}
        className="flex items-center justify-between gap-4 px-5 py-4 hover:bg-slate-50"
      >
        <div>
          <p className="font-medium text-slate-900">{child.full_name}</p>
          <p className="text-sm text-slate-500">
            {child.school_class ? child.school_class.name : "No class yet"} ·{" "}
            <span className="font-mono text-xs">{child.admission_number}</span>
          </p>
        </div>
        <div className="flex items-center gap-3">
          {child.status === "inactive" ? <Badge tone="slate">Withdrawn</Badge> : null}
          <span className="text-sm font-medium text-indigo-600">View fees →</span>
        </div>
      </Link>
    </li>
  );
}
