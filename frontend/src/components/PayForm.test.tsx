import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../lib/api";
import { PayForm } from "./PayForm";

function setup(props: Partial<Parameters<typeof PayForm>[0]> = {}) {
  const onSubmit = vi.fn().mockResolvedValue(undefined);
  render(
    <PayForm
      outstanding="55.00"
      submitLabel="Record payment"
      busyLabel="Recording…"
      onSubmit={onSubmit}
      {...props}
    />,
  );
  return { onSubmit, user: userEvent.setup() };
}

describe("PayForm", () => {
  it("starts at the full outstanding amount, which is what most people pay", () => {
    setup();
    expect(screen.getByLabelText("Amount")).toHaveValue("55.00");
  });

  it("says what is owed", () => {
    setup();
    expect(screen.getByText(/55\.00 still owed/)).toBeInTheDocument();
  });

  it("submits the amount as a string, untouched", async () => {
    const { onSubmit, user } = setup();
    await user.clear(screen.getByLabelText("Amount"));
    await user.type(screen.getByLabelText("Amount"), "20.50");
    await user.click(screen.getByRole("button", { name: "Record payment" }));

    expect(onSubmit).toHaveBeenCalledWith("20.50");
  });

  it("refuses more than is owed without asking the server", async () => {
    const { onSubmit, user } = setup();
    await user.clear(screen.getByLabelText("Amount"));
    await user.type(screen.getByLabelText("Amount"), "60.00");
    await user.click(screen.getByRole("button", { name: "Record payment" }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(await screen.findByRole("alert")).toHaveTextContent(/more than/);
  });

  it("refuses zero", async () => {
    const { onSubmit, user } = setup();
    await user.clear(screen.getByLabelText("Amount"));
    await user.type(screen.getByLabelText("Amount"), "0");
    await user.click(screen.getByRole("button", { name: "Record payment" }));

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("shows the server's refusal, because the balance can move while the form is open", async () => {
    const onSubmit = vi
      .fn()
      .mockRejectedValue(new ApiError(409, "Payment of 55.00 exceeds the 20.00 still owed."));
    const { user } = setup({ onSubmit });

    await user.click(screen.getByRole("button", { name: "Record payment" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("exceeds the 20.00 still owed");
  });

  it("lets the user try again after the server refuses", async () => {
    const onSubmit = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(409, "Payment of 55.00 exceeds the 20.00 still owed."))
      .mockResolvedValueOnce(undefined);
    const { user } = setup({ onSubmit });

    await user.click(screen.getByRole("button", { name: "Record payment" }));
    await screen.findByRole("alert");

    await user.clear(screen.getByLabelText("Amount"));
    await user.type(screen.getByLabelText("Amount"), "20.00");
    await user.click(screen.getByRole("button", { name: "Record payment" }));

    expect(onSubmit).toHaveBeenLastCalledWith("20.00");
  });

  it("refills the full amount with Pay it all", async () => {
    const { user } = setup();
    await user.clear(screen.getByLabelText("Amount"));
    await user.type(screen.getByLabelText("Amount"), "1.00");
    await user.click(screen.getByRole("button", { name: "Pay it all" }));

    expect(screen.getByLabelText("Amount")).toHaveValue("55.00");
  });

  it("does not submit twice while the first is in flight", async () => {
    let release: () => void = () => {};
    const onSubmit = vi.fn().mockReturnValue(new Promise<void>((resolve) => (release = resolve)));
    const { user } = setup({ onSubmit });

    await user.click(screen.getByRole("button", { name: "Record payment" }));
    expect(screen.getByRole("button", { name: "Recording…" })).toBeDisabled();

    release();
    expect(onSubmit).toHaveBeenCalledOnce();
  });
});
