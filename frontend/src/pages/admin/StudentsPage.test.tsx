import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "../../test/render";
import { StudentsPage } from "./StudentsPage";

const STUDENT = {
  id: 7,
  full_name: "Ama Mensah",
  admission_number: "SKU-2026-001",
  first_name: "Ama",
  last_name: "Mensah",
  status: "active",
  school_class: { id: 1, name: "Grade 4A", academic_year: "2026" },
  parent: { id: 5, name: "Abena Owusu", email: "abena@example.com" },
};

let fetchMock: ReturnType<typeof vi.fn>;
let patched: { url: string; body: Record<string, unknown> } | null;

beforeEach(() => {
  localStorage.setItem("sukuu.token", "a-token");
  patched = null;

  fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
    const target = String(url);
    if (init?.method === "PATCH") {
      patched = { url: target, body: JSON.parse(String(init.body)) };
      return Promise.resolve(
        new Response(JSON.stringify(STUDENT), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    const body = target.includes("/classes")
      ? { items: [{ id: 1, name: "Grade 4A", academic_year: "2026", archived_at: null, active_student_count: 6 },
                  { id: 2, name: "Grade 5B", academic_year: "2026", archived_at: null, active_student_count: 6 }],
          total: 2, limit: 200, offset: 0 }
      : target.includes("/users")
        ? { items: [{ id: 5, name: "Abena Owusu", email: "abena@example.com", role: "parent" }],
            total: 1, limit: 200, offset: 0 }
        : { items: [STUDENT], total: 1, limit: 25, offset: 0 };

    return Promise.resolve(
      new Response(JSON.stringify(body), {
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

async function openTheEditor() {
  const user = userEvent.setup();
  renderWithProviders(<StudentsPage />, { route: "/students" });
  await screen.findByText("Ama Mensah");
  await user.click(screen.getByRole("button", { name: "Edit" }));
  await screen.findByLabelText("Class");
  return user;
}

describe("editing a student", () => {
  it("moves them to another class", async () => {
    // The gap this closes: a student changes class every year, and enrolment
    // was previously the only chance to say which one.
    const user = await openTheEditor();

    await user.selectOptions(screen.getByLabelText("Class"), "2");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(patched).not.toBeNull());
    expect(patched!.url).toContain("/students/7");
    expect(patched!.body.class_id).toBe(2);
  });

  it("detaches a class with an explicit null, not by omitting it", async () => {
    // The API tells "leave it alone" apart from "clear it" by whether the key
    // is present. Omitting it here would silently mean the opposite.
    const user = await openTheEditor();

    await user.selectOptions(screen.getByLabelText("Class"), "");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(patched).not.toBeNull());
    expect(patched!.body).toHaveProperty("class_id");
    expect(patched!.body.class_id).toBeNull();
  });

  it("attaches a parent after enrolment", async () => {
    const user = await openTheEditor();

    await user.selectOptions(screen.getByLabelText("Parent"), "5");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(patched).not.toBeNull());
    expect(patched!.body.parent_id).toBe(5);
  });

  it("corrects a name and an admission number", async () => {
    const user = await openTheEditor();

    await user.clear(screen.getByLabelText("First name"));
    await user.type(screen.getByLabelText("First name"), "Akosua");
    await user.clear(screen.getByLabelText("Admission number"));
    await user.type(screen.getByLabelText("Admission number"), "SKU-2026-099");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(patched).not.toBeNull());
    expect(patched!.body.first_name).toBe("Akosua");
    expect(patched!.body.admission_number).toBe("SKU-2026-099");
  });

  it("keeps the editor open and says why when the API refuses", async () => {
    const user = await openTheEditor();

    fetchMock.mockImplementationOnce(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({ detail: "A student with that admission number already exists." }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("already exists");
    // Still editing: closing on failure would throw away what was typed.
    expect(screen.getByLabelText("Class")).toBeInTheDocument();
  });

  it("cancels without saving anything", async () => {
    const user = await openTheEditor();

    await user.selectOptions(screen.getByLabelText("Class"), "2");
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByLabelText("Class")).not.toBeInTheDocument());
    expect(patched).toBeNull();
  });

  it("toggles status without opening the editor", async () => {
    const user = userEvent.setup();
    renderWithProviders(<StudentsPage />, { route: "/students" });
    await screen.findByText("Ama Mensah");

    await user.click(screen.getByTitle("Mark as withdrawn"));

    await waitFor(() => expect(patched).not.toBeNull());
    expect(patched!.body).toEqual({ status: "inactive" });
  });
});

describe("the roll", () => {
  it("shows who a student belongs to", async () => {
    renderWithProviders(<StudentsPage />, { route: "/students" });
    const row = (await screen.findByText("Ama Mensah")).closest("tr")!;
    expect(within(row).getByText("Grade 4A")).toBeInTheDocument();
    expect(within(row).getByText("abena@example.com")).toBeInTheDocument();
  });
});
