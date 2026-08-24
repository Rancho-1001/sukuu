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
import { useCreateFeeType, useFeeTypes } from "../../lib/queries";

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
              </tr>
            }
          >
            {data?.items.map((feeType) => (
              <tr key={feeType.id}>
                <Td>
                  <span className="font-medium text-slate-900">{feeType.name}</span>
                  {feeType.description ? (
                    <p className="text-sm text-slate-500">{feeType.description}</p>
                  ) : null}
                </Td>
                <Td>{PERIODS.find((p) => p.value === feeType.billing_period)?.label}</Td>
                <Td align="right">
                  <Amount value={feeType.default_amount} />
                </Td>
              </tr>
            ))}
          </Table>
          <Pager total={data?.total ?? 0} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
        </DataState>
      </Card>
    </div>
  );
}
