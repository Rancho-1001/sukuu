import { useState } from "react";

import { FormCard } from "../../components/FormCard";
import { Badge, Button, Card, CardHeader, DataState, Input, Pager, Select, Table, Td, Th } from "../../components/ui";
import { useArchiveClass, useClasses, useCreateClass, useUpdateClass } from "../../lib/queries";
import type { SchoolClass } from "../../lib/types";
import { ApiError } from "../../lib/api";
import { Banner } from "../../components/ui";
import { Field } from "../../components/ui";

const PAGE_SIZE = 25;

export function ClassesPage() {
  const [offset, setOffset] = useState(0);
  const [includeArchived, setIncludeArchived] = useState(false);
  const { data, isPending, error } = useClasses({
    include_archived: includeArchived,
    limit: PAGE_SIZE,
    offset,
  });
  const create = useCreateClass();
  const archive = useArchiveClass();
  const [editingId, setEditingId] = useState<number | null>(null);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Classes</h1>
        <p className="mt-1 text-sm text-slate-500">
          Classes are archived at the end of a year, never deleted — the students who were in
          them keep pointing at them.
        </p>
      </div>

      <FormCard
        title="Add a class"
        openLabel="New class"
        submitLabel="Create class"
        onSubmit={async (form) => {
          const created = await create.mutateAsync({
            name: String(form.get("name") ?? ""),
            academic_year: String(form.get("academic_year") ?? ""),
          });
          return `${created.name} created for ${created.academic_year}.`;
        }}
      >
        {(error) => (
          <>
            <Field label="Name" error={error?.fieldError("name")}>
              <Input name="name" placeholder="Grade 5B" required />
            </Field>
            <Field label="Academic year" error={error?.fieldError("academic_year")}>
              <Input name="academic_year" placeholder="2026" required />
            </Field>
          </>
        )}
      </FormCard>

      <Card>
        <CardHeader
          title="All classes"
          subtitle={data ? `${data.total} total` : undefined}
          actions={
            <Select
              aria-label="Show"
              value={includeArchived ? "all" : "active"}
              onChange={(event) => {
                setIncludeArchived(event.target.value === "all");
                setOffset(0);
              }}
            >
              <option value="active">Active only</option>
              <option value="all">Include archived</option>
            </Select>
          }
        />
        <DataState
          isPending={isPending}
          error={error}
          isEmpty={data?.items.length === 0}
          emptyMessage="No classes yet. Add the first one above."
        >
          <Table
            head={
              <tr>
                <Th>Class</Th>
                <Th>Year</Th>
                <Th align="right">Students</Th>
                <Th align="right">Action</Th>
              </tr>
            }
          >
            {data?.items.map((schoolClass) => (
              <ClassRow
                key={schoolClass.id}
                schoolClass={schoolClass}
                isEditing={editingId === schoolClass.id}
                onEdit={() => setEditingId(schoolClass.id)}
                onDone={() => setEditingId(null)}
                onArchive={() =>
                  archive.mutate({
                    id: schoolClass.id,
                    archived: schoolClass.archived_at !== null,
                  })
                }
                archiving={archive.isPending}
              />
            ))}
          </Table>
          <Pager total={data?.total ?? 0} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
        </DataState>
      </Card>
    </div>
  );
}

function ClassRow({
  schoolClass,
  isEditing,
  onEdit,
  onDone,
  onArchive,
  archiving,
}: {
  schoolClass: SchoolClass;
  isEditing: boolean;
  onEdit: () => void;
  onDone: () => void;
  onArchive: () => void;
  archiving: boolean;
}) {
  const update = useUpdateClass();
  const [error, setError] = useState<ApiError | null>(null);

  if (isEditing) {
    return (
      <tr className="bg-slate-50">
        <td colSpan={4} className="px-5 py-4">
          {error ? (
            <div className="mb-3">
              <Banner>{error.message}</Banner>
            </div>
          ) : null}
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={async (event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              setError(null);
              try {
                await update.mutateAsync({
                  id: schoolClass.id,
                  name: String(form.get("name") ?? ""),
                  academic_year: String(form.get("academic_year") ?? ""),
                });
                onDone();
              } catch (caught) {
                setError(
                  caught instanceof ApiError ? caught : new ApiError(0, "Could not save."),
                );
              }
            }}
          >
            <div className="w-48">
              <Field label="Name" error={error?.fieldError("name")}>
                <Input name="name" defaultValue={schoolClass.name} required />
              </Field>
            </div>
            <div className="w-32">
              <Field label="Academic year" error={error?.fieldError("academic_year")}>
                <Input name="academic_year" defaultValue={schoolClass.academic_year} required />
              </Field>
            </div>
            <Button type="submit" disabled={update.isPending}>
              {update.isPending ? "Saving…" : "Save"}
            </Button>
            <Button type="button" variant="ghost" onClick={onDone}>
              Cancel
            </Button>
          </form>
        </td>
      </tr>
    );
  }

  return (
    <tr>
      <Td>
        <span className="font-medium text-slate-900">{schoolClass.name}</span>
        {schoolClass.archived_at ? (
          <span className="ml-2">
            <Badge tone="slate">Archived</Badge>
          </span>
        ) : null}
      </Td>
      <Td>{schoolClass.academic_year}</Td>
      <Td align="right">{schoolClass.active_student_count}</Td>
      <Td align="right">
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onEdit}>
            Rename
          </Button>
          <Button variant="secondary" disabled={archiving} onClick={onArchive}>
            {schoolClass.archived_at ? "Restore" : "Archive"}
          </Button>
        </div>
      </Td>
    </tr>
  );
}
