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
import type { ClassSummary, Student, User } from "../../lib/types";
import { ApiError } from "../../lib/api";
import { Banner, Button } from "../../components/ui";

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
  const [editingId, setEditingId] = useState<number | null>(null);

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
                aria-label="Filter by class"
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
                <Th align="right">Status</Th>
                {isAdmin ? <Th align="right">Action</Th> : null}
              </tr>
            }
          >
            {data?.items.map((student) => (
              <StudentRow
                key={student.id}
                student={student}
                isAdmin={isAdmin}
                classes={classes.data?.items ?? []}
                parents={parents.data?.items ?? []}
                isEditing={editingId === student.id}
                onEdit={() => setEditingId(student.id)}
                onDone={() => setEditingId(null)}
              />
            ))}
          </Table>
          <Pager total={data?.total ?? 0} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
        </DataState>
      </Card>
    </div>
  );
}

function StudentRow({
  student,
  isAdmin,
  classes,
  parents,
  isEditing,
  onEdit,
  onDone,
}: {
  student: Student;
  isAdmin: boolean;
  classes: ClassSummary[];
  parents: User[];
  isEditing: boolean;
  onEdit: () => void;
  onDone: () => void;
}) {
  const update = useUpdateStudent();
  const [error, setError] = useState<ApiError | null>(null);

  async function save(changes: Record<string, unknown>) {
    setError(null);
    try {
      await update.mutateAsync({ id: student.id, ...changes });
      return true;
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError(0, "Could not save."));
      return false;
    }
  }

  if (isEditing) {
    return (
      <tr className="bg-slate-50">
        <td colSpan={5} className="px-5 py-4">
          {error ? (
            <div className="mb-3">
              <Banner>{error.message}</Banner>
            </div>
          ) : null}
          <form
            className="grid gap-4 sm:grid-cols-2"
            onSubmit={async (event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              const saved = await save({
                first_name: String(form.get("first_name") ?? ""),
                last_name: String(form.get("last_name") ?? ""),
                admission_number: String(form.get("admission_number") ?? ""),
                // An empty select means "no class" - sent as an explicit null,
                // which is how the API tells "detach" apart from "leave alone".
                class_id: form.get("class_id") ? Number(form.get("class_id")) : null,
                parent_id: form.get("parent_id") ? Number(form.get("parent_id")) : null,
              });
              if (saved) onDone();
            }}
          >
            <Field label="First name" error={error?.fieldError("first_name")}>
              <Input name="first_name" defaultValue={student.first_name} required />
            </Field>
            <Field label="Last name" error={error?.fieldError("last_name")}>
              <Input name="last_name" defaultValue={student.last_name} required />
            </Field>
            <Field label="Admission number" error={error?.fieldError("admission_number")}>
              <Input name="admission_number" defaultValue={student.admission_number} required />
            </Field>
            <Field label="Class" error={error?.fieldError("class_id")}>
              <Select name="class_id" defaultValue={student.school_class?.id ?? ""}>
                <option value="">No class</option>
                {classes.map((schoolClass) => (
                  <option key={schoolClass.id} value={schoolClass.id}>
                    {schoolClass.name} · {schoolClass.academic_year}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Parent" error={error?.fieldError("parent_id")}>
              <Select name="parent_id" defaultValue={student.parent?.id ?? ""}>
                <option value="">No parent</option>
                {parents.map((parent) => (
                  <option key={parent.id} value={parent.id}>
                    {parent.name} · {parent.email}
                  </option>
                ))}
              </Select>
            </Field>
            <div className="flex gap-2 sm:col-span-2">
              <Button type="submit" disabled={update.isPending}>
                {update.isPending ? "Saving…" : "Save"}
              </Button>
              <Button type="button" variant="ghost" onClick={onDone}>
                Cancel
              </Button>
            </div>
          </form>
        </td>
      </tr>
    );
  }

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
      <Td align="right">
        {isAdmin ? (
          <button
            type="button"
            disabled={update.isPending}
            className="disabled:opacity-50"
            title={student.status === "active" ? "Mark as withdrawn" : "Mark as active"}
            onClick={() => save({ status: student.status === "active" ? "inactive" : "active" })}
          >
            <Badge tone={student.status === "active" ? "green" : "slate"}>
              {student.status === "active" ? "Active" : "Withdrawn"}
            </Badge>
          </button>
        ) : (
          <Badge tone={student.status === "active" ? "green" : "slate"}>
            {student.status === "active" ? "Active" : "Withdrawn"}
          </Badge>
        )}
      </Td>
      {isAdmin ? (
        <Td align="right">
          <Button variant="ghost" onClick={onEdit}>
            Edit
          </Button>
        </Td>
      ) : null}
    </tr>
  );
}
