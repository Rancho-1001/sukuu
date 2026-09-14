import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "../../test/render";
import { PaymentCancelledPage, PaymentSuccessPage } from "./PaymentResultPage";

function balanceWith(amountPaid: string) {
  return {
    student: { id: 7, full_name: "Ama Mensah", admission_number: "SKU-1" },
    school_class: null,
    parent: null,
    billed: "85.00",
    paid: amountPaid,
    outstanding: "0.00",
    lines: [
      {
        id: 3,
        amount: "85.00",
        amount_paid: amountPaid,
        outstanding: "0.00",
        settled: amountPaid === "85.00",
        due_date: null,
        period_label: "Intake 2026",
        student: { id: 7, full_name: "Ama Mensah", admission_number: "SKU-1" },
        fee_type: { id: 1, name: "Uniform", billing_period: "one_time" },
      },
    ],
  };
}

let responses: string[];
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  localStorage.setItem("sukuu.token", "t");
  responses = [];
  fetchMock = vi.fn().mockImplementation(() => {
    // Each poll gets the next balance in the script; the last one repeats.
    const paid = responses.length > 1 ? responses.shift()! : responses[0];
    return Promise.resolve(
      new Response(JSON.stringify(balanceWith(paid)), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("the success page", () => {
  it("does not claim success on arrival - only the webhook can", async () => {
    // The balance still shows what it did before checkout: the webhook has
    // not landed. Saying "paid" here would be saying it on Stripe's redirect,
    // which anyone can issue by typing the URL.
    responses = ["20.00"];
    renderWithProviders(<PaymentSuccessPage />, {
      route: "/payments/success?student=7&fee=3&paid_before=20.00",
      role: "parent",
    });

    expect(await screen.findByText("Confirming your payment")).toBeInTheDocument();
    expect(screen.queryByText("Payment confirmed")).not.toBeInTheDocument();
  });

  it("confirms once the balance moves past paid_before", async () => {
    responses = ["50.00"];
    renderWithProviders(<PaymentSuccessPage />, {
      route: "/payments/success?student=7&fee=3&paid_before=20.00",
      role: "parent",
    });

    expect(await screen.findByText("Payment confirmed")).toBeInTheDocument();
    expect(screen.getByText(/Uniform/)).toBeInTheDocument();
    expect(screen.getByText(/50\.00/)).toBeInTheDocument();
  });

  it("says when the fee is now settled", async () => {
    responses = ["85.00"];
    renderWithProviders(<PaymentSuccessPage />, {
      route: "/payments/success?student=7&fee=3&paid_before=55.00",
      role: "parent",
    });

    expect(await screen.findByText("This fee is now settled.")).toBeInTheDocument();
  });

  it("keeps polling until the webhook lands", async () => {
    // First answer: unchanged. Later answer: landed. The page has to ask again
    // rather than settle for the first thing it hears.
    responses = ["20.00", "20.00", "50.00"];
    renderWithProviders(<PaymentSuccessPage />, {
      route: "/payments/success?student=7&fee=3&paid_before=20.00",
      role: "parent",
    });

    expect(await screen.findByText("Confirming your payment")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Payment confirmed")).toBeInTheDocument(), {
      timeout: 12_000,
    });
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(3);
  }, 15_000);

  it("links back to the right child", async () => {
    responses = ["50.00"];
    renderWithProviders(<PaymentSuccessPage />, {
      route: "/payments/success?student=7&fee=3&paid_before=20.00",
      role: "parent",
    });

    await screen.findByText("Payment confirmed");
    expect(screen.getByRole("link", { name: "Back to fees" })).toHaveAttribute(
      "href",
      "/my-children/7",
    );
  });

  it("still says thank you when the URL carries no context", async () => {
    responses = ["20.00"];
    renderWithProviders(<PaymentSuccessPage />, {
      route: "/payments/success",
      role: "parent",
    });

    expect(await screen.findByText("Thank you")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("the cancelled page", () => {
  it("says nothing was taken and goes back to the child", () => {
    renderWithProviders(<PaymentCancelledPage />, {
      route: "/payments/cancelled?student=7&fee=3&paid_before=20.00",
      role: "parent",
    });

    expect(screen.getByText("Payment cancelled")).toBeInTheDocument();
    expect(screen.getByText(/No payment was taken/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to fees" })).toHaveAttribute(
      "href",
      "/my-children/7",
    );
  });
});
