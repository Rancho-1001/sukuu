import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../lib/api";
import { FormCard } from "./FormCard";
import { Field, Input } from "./ui";

function setup(onSubmit: (form: FormData) => Promise<string | void>) {
  render(
    <FormCard title="Add a class" openLabel="New class" submitLabel="Create" onSubmit={onSubmit}>
      {(error) => (
        <Field label="Name" error={error?.fieldError("name")}>
          <Input name="name" defaultValue="Grade 5B" />
        </Field>
      )}
    </FormCard>,
  );
  return userEvent.setup();
}

describe("FormCard", () => {
  it("stays closed until asked, so the list is not pushed down the page", () => {
    setup(vi.fn());
    expect(screen.queryByLabelText("Name")).not.toBeInTheDocument();
  });

  it("submits the fields", async () => {
    const onSubmit = vi.fn().mockResolvedValue("Created.");
    const user = setup(onSubmit);

    await user.click(screen.getByRole("button", { name: "New class" }));
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(onSubmit.mock.calls[0][0].get("name")).toBe("Grade 5B");
  });

  it("does not report an error when it succeeded", async () => {
    // The bug this pins: `event.currentTarget` is null once the handler has
    // returned, so resetting the form after an await threw, and the throw
    // landed in the catch - putting an error banner under a success message.
    const user = setup(vi.fn().mockResolvedValue("Created."));

    await user.click(screen.getByRole("button", { name: "New class" }));
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText("Created.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("clears the form after a save, ready for the next one", async () => {
    const user = setup(vi.fn().mockResolvedValue("Created."));

    await user.click(screen.getByRole("button", { name: "New class" }));
    await user.clear(screen.getByLabelText("Name"));
    await user.type(screen.getByLabelText("Name"), "Grade 6A");
    await user.click(screen.getByRole("button", { name: "Create" }));

    await screen.findByText("Created.");
    expect(screen.getByLabelText("Name")).toHaveValue("Grade 5B");
  });

  it("shows the API's sentence when it refuses", async () => {
    const user = setup(
      vi.fn().mockRejectedValue(new ApiError(409, "That class already exists for that year.")),
    );

    await user.click(screen.getByRole("button", { name: "New class" }));
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("already exists");
  });

  it("puts a field error next to the field the API blamed", async () => {
    const user = setup(
      vi.fn().mockRejectedValue(
        new ApiError(422, "name: must not be blank", [
          { field: "name", message: "must not be blank" },
        ]),
      ),
    );

    await user.click(screen.getByRole("button", { name: "New class" }));
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText("must not be blank")).toBeInTheDocument();
  });
});
