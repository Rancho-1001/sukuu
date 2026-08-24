import { useState } from "react";

import { FormCard } from "../../components/FormCard";
import {
  Badge,
  Card,
  CardHeader,
  DataState,
  Field,
  Input,
  Pager,
  Select,
  Table,
  Td,
  Th,
} from "../../components/ui";
import { useAuth } from "../../auth/context";
import { useClasses, useCreateStudent, useStudents, useUpdateStudent, useUsers } from "../../lib/queries";
import type { Student } from "../../lib/types";

const PAGE_SIZE = 25;

export function StudentsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  const [search, setSearch] = useState("");
  const [classId, setClassId] = useState<number | undefined>();
  const [offset, setOffset] = useState(0);

  const classes = useClasses({ limit: 200 });
  // Only an admin may read the account directory, so the picker is only
  // fetched for one. A bursar reaching this page still gets the roster.
  const parents = useUsers(isAdmin ? { role: "parent", limit: 200 } : { limit: 0 });
  const { data, isPending, error } = useStudents({
    q: search || undefined,
    class_id: classId,
    limit: PAGE_SIZE,
    offset,
  });
  const create = useCreateStudent();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Students</h1>
        <p className="mt-1 text-sm text-slate-500">The roll, and who each child belongs to.</p>
      </div>

      {isAdmin ? (
        <FormCard
          title="Enrol a student"
          subtitle="A class and a parent can be attached now or later."
          openLabel="New student"
          submitLabel="Enrol student"
          onSubmit={async (form) => {
            const created = await create.mutateAsync({
              first_name: String(form.get("first_name") ?? ""),
              last_name: String(form.get("last_name") ?? ""),
              admission_number: String(form.get("admission_number") ?? ""),
              class_id: form.get("class_id") ? Number(form.get("class_id")) : null,
              parent_id: form.get("parent_id") ? Number(form.get("parent_id")) : null,
            });
            return `${created.full_name} enrolled.`;
          }}
        >
          {(error) => (
            <>
              <Field label="First name" error={error?.fieldError("first_name")}>
                <Input name="first_name" required />
              </Field>
              <Field label="Last name" error={error?.fieldError("last_name")}>
                <Input name="last_name" required />
              </Field>
              <Field label="Admission number" error={error?.fieldError("admission_number")}>
                <Input name="admission_number" placeholder="SKU-2026-001" required />
              </Field>
              <Field label="Class" error={error?.fieldError("class_id")}>
                <Select name="class_id" defaultValue="">
                  <option value="">No class yet</option>
                  {classes.data?.items.map((schoolClass) => (
                    <option key={schoolClass.id} value={schoolClass.id}>
                      {schoolClass.name} · {schoolClass.academic_year}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field
                label="Parent"
                error={error?.fieldError("parent_id")}
                hint="Accounts are created by the seed script in this version."
              >
                <Select name="parent_id" defaultValue="">
                  <option value="">No parent yet</option>
                  {parents.data?.items.map((parent) => (
                    <option key={parent.id} value={parent.id}>
                      {parent.name} · {parent.email}
                    </option>
                  ))}
                </Select>
              </Field>
            </>
          )}
        </FormCard>
      ) : null}

      <Card>
        <CardHeader
          title="Roll"
          subtitle={data ? `${data.total} students` : undefined}
          actions={
            <>
              <Input
                aria-label="Search students"
                placeholder="Name or admission number"
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value);
                  setOffset(0);
                }}
              />
              <Select
                aria-label="Class"
                value={classId ?? ""}
                onChange={(event) => {
                  setClassId(event.target.value ? Number(event.target.value) : undefined);
                  setOffset(0);
                }}
              >
                <option value="">All classes</option>
                {classes.data?.items.map((schoolClass) => (
                  <option key={schoolClass.id} value={schoolClass.id}>
                    {schoolClass.name}
                  </option>
                ))}
              </Select>
            </>
          }
        />
        <DataState
          isPending={isPending}
          error={error}
          isEmpty={data?.items.length === 0}
          emptyMessage={search ? `Nobody matches “${search}”.` : "No students yet."}
        >
          <Table
            head={
              <tr>
                <Th>Student</Th>
                <Th>Class</Th>
                <Th>Parent</Th>
                {isAdmin ? <Th align="right">Status</Th> : null}
              </tr>
            }
          >
            {data?.items.map((student) => (
              <StudentRow key={student.id} student={student} isAdmin={isAdmin} />
            ))}
          </Table>
          <Pager total={data?.total ?? 0} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
        </DataState>
      </Card>
    </div>
  );
}

function StudentRow({ student, isAdmin }: { student: Student; isAdmin: boolean }) {
  const update = useUpdateStudent();

  return (
    <tr>
      <Td>
        <span className="font-medium text-slate-900">{student.full_name}</span>
        <span className="ml-2 font-mono text-xs text-slate-400">{student.admission_number}</span>
      </Td>
      <Td>{student.school_class?.name ?? <span className="text-slate-400">Unplaced</span>}</Td>
      <Td>
        {student.parent ? (
          <>
            {student.parent.name}
            <span className="block text-xs text-slate-400">{student.parent.email}</span>
          </>
        ) : (
          <span className="text-slate-400">None</span>
        )}
      </Td>
      {isAdmin ? (
        <Td align="right">
          <button
            type="button"
            disabled={update.isPending}
            className="disabled:opacity-50"
            title={student.status === "active" ? "Mark as withdrawn" : "Mark as active"}
            onClick={() =>
              update.mutate({
                id: student.id,
                status: student.status === "active" ? "inactive" : "active",
              })
            }
          >
            <Badge tone={student.status === "active" ? "green" : "slate"}>
              {student.status === "active" ? "Active" : "Withdrawn"}
            </Badge>
          </button>
        </Td>
      ) : null}
    </tr>
  );
}
