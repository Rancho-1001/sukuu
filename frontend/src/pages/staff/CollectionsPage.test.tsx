import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders, requestedUrls } from "../../test/render";
import { CollectionsPage } from "./CollectionsPage";

function page(items: unknown[] = []) {
  return { items, total: items.length, limit: 25, offset: 0 };
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  localStorage.setItem("sukuu.token", "a-token");
  fetchMock = vi.fn().mockImplementation((url: string) =>
    Promise.resolve(
      new Response(
        JSON.stringify(
          String(url).includes("/classes")
            ? page([{ id: 3, name: "Grade 5A", academic_year: "2026", archived_at: null, active_student_count: 6 }])
            : page(),
        ),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    ),
  );
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("the class filter lives in the URL", () => {
  it("applies a class_id it was linked to", async () => {
    // The dashboard links straight here. With the filter in component state
    // that link navigated and then showed every fee in the school - which
    // looks like it worked, and is the worst kind of broken.
    renderWithProviders(<CollectionsPage />, { route: "/collections?class_id=3" });

    await waitFor(() => {
      const asked = requestedUrls(fetchMock).filter((url) => url.includes("/fee-assignments"));
      expect(asked.some((url) => url.includes("class_id=3"))).toBe(true);
    });
  });

  it("shows that class as the selected one", async () => {
    renderWithProviders(<CollectionsPage />, { route: "/collections?class_id=3" });
    await waitFor(() => expect(screen.getByLabelText("Filter by class")).toHaveValue("3"));
  });

  it("asks for every class when there is no class_id", async () => {
    renderWithProviders(<CollectionsPage />, { route: "/collections" });

    await waitFor(() => {
      const asked = requestedUrls(fetchMock).filter((url) => url.includes("/fee-assignments"));
      expect(asked.length).toBeGreaterThan(0);
      expect(asked.every((url) => !url.includes("class_id"))).toBe(true);
    });
  });

  it("puts a chosen class into the URL so the view can be sent to someone", async () => {
    const user = userEvent.setup();
    renderWithProviders(<CollectionsPage />, { route: "/collections" });

    await screen.findByRole("option", { name: /Grade 5A/ });
    await user.selectOptions(screen.getByLabelText("Filter by class"), "3");

    await waitFor(() => {
      const asked = requestedUrls(fetchMock).filter((url) => url.includes("/fee-assignments"));
      expect(asked.some((url) => url.includes("class_id=3"))).toBe(true);
    });
  });

  it("defaults to unpaid only, which is the question asked at a desk", async () => {
    renderWithProviders(<CollectionsPage />, { route: "/collections" });

    await waitFor(() => {
      const asked = requestedUrls(fetchMock).filter((url) => url.includes("/fee-assignments"));
      expect(asked.some((url) => url.includes("outstanding_only=true"))).toBe(true);
    });
  });
});
