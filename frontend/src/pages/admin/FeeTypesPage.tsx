import { useState } from "react";

import { FormCard } from "../../components/FormCard";
import {
  Amount,
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
import { useCreateFeeType, useFeeTypes, useUpdateFeeType } from "../../lib/queries";
import { ApiError } from "../../lib/api";
import { Banner, Button } from "../../components/ui";
import type { FeeType } from "../../lib/types";

const PAGE_SIZE = 25;

const PERIODS = [
  { value: "term", label: "Per term" },
  { value: "monthly", label: "Monthly" },
  { value: "one_time", label: "One-off" },
];

export function FeeTypesPage() {
  const [offset, setOffset] = useState(0);
  const { data, isPending, error } = useFeeTypes({ limit: PAGE_SIZE, offset });
  const create = useCreateFeeType();
  const [editingId, setEditingId] = useState<number | null>(null);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Fee types</h1>
        <p className="mt-1 text-sm text-slate-500">
          The catalogue of what the school charges for. Changing a default amount does not
          touch fees already assigned.
        </p>
      </div>

      <FormCard
        title="Add a fee type"
        openLabel="New fee type"
        submitLabel="Create fee type"
        onSubmit={async (form) => {
          const created = await create.mutateAsync({
            name: String(form.get("name") ?? ""),
            description: String(form.get("description") ?? "") || null,
            default_amount: String(form.get("default_amount") ?? ""),
            billing_period: String(form.get("billing_period") ?? "term"),
          });
          return `${created.name} added.`;
        }}
      >
        {(error) => (
          <>
            <Field label="Name" error={error?.fieldError("name")}>
              <Input name="name" placeholder="Tuition" required />
            </Field>
            <Field
              label="Default amount"
              error={error?.fieldError("default_amount")}
              hint="Two decimal places, e.g. 250.00"
            >
              <Input name="default_amount" inputMode="decimal" placeholder="250.00" required />
            </Field>
            <Field label="Billing period" error={error?.fieldError("billing_period")}>
              <Select name="billing_period" defaultValue="term">
                {PERIODS.map((period) => (
                  <option key={period.value} value={period.value}>
                    {period.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Description" error={error?.fieldError("description")}>
              <Input name="description" placeholder="Optional" />
            </Field>
          </>
        )}
      </FormCard>

      <Card>
        <CardHeader title="Catalogue" subtitle={data ? `${data.total} total` : undefined} />
        <DataState
          isPending={isPending}
          error={error}
          isEmpty={data?.items.length === 0}
          emptyMessage="No fee types yet. Add one above before assigning fees."
        >
          <Table
            head={
              <tr>
                <Th>Fee</Th>
                <Th>Billing</Th>
                <Th align="right">Default</Th>
                <Th align="right">Action</Th>
              </tr>
            }
          >
            {data?.items.map((feeType) => (
              <FeeTypeRow
                key={feeType.id}
                feeType={feeType}
                isEditing={editingId === feeType.id}
                onEdit={() => setEditingId(feeType.id)}
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

function FeeTypeRow({
  feeType,
  isEditing,
  onEdit,
  onDone,
}: {
  feeType: FeeType;
  isEditing: boolean;
  onEdit: () => void;
  onDone: () => void;
}) {
  const update = useUpdateFeeType();
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
            className="grid gap-4 sm:grid-cols-2"
            onSubmit={async (event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              setError(null);
              try {
                await update.mutateAsync({
                  id: feeType.id,
                  name: String(form.get("name") ?? ""),
                  description: String(form.get("description") ?? "") || null,
                  default_amount: String(form.get("default_amount") ?? ""),
                  billing_period: String(form.get("billing_period") ?? "term"),
                });
                onDone();
              } catch (caught) {
                setError(caught instanceof ApiError ? caught : new ApiError(0, "Could not save."));
              }
            }}
          >
            <Field label="Name" error={error?.fieldError("name")}>
              <Input name="name" defaultValue={feeType.name} required />
            </Field>
            <Field
              label="Default amount"
              error={error?.fieldError("default_amount")}
              hint="Fees already assigned keep what they were billed at."
            >
              <Input
                name="default_amount"
                inputMode="decimal"
                defaultValue={feeType.default_amount}
                required
              />
            </Field>
            <Field label="Billing period" error={error?.fieldError("billing_period")}>
              <Select name="billing_period" defaultValue={feeType.billing_period}>
                {PERIODS.map((period) => (
                  <option key={period.value} value={period.value}>
                    {period.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Description" error={error?.fieldError("description")}>
              <Input name="description" defaultValue={feeType.description ?? ""} />
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
        <span className="font-medium text-slate-900">{feeType.name}</span>
        {feeType.description ? (
          <p className="text-sm text-slate-500">{feeType.description}</p>
        ) : null}
      </Td>
      <Td>{PERIODS.find((period) => period.value === feeType.billing_period)?.label}</Td>
      <Td align="right">
        <Amount value={feeType.default_amount} />
      </Td>
      <Td align="right">
        <Button variant="ghost" onClick={onEdit}>
          Edit
        </Button>
      </Td>
    </tr>
  );
}
