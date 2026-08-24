import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, query, readToken, setSessionExpiredHandler, writeToken } from "./api";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  localStorage.clear();
  setSessionExpiredHandler(() => {});
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("token attachment", () => {
  it("sends the bearer token once there is one", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    writeToken("a-token");

    await api.get("/auth/me");

    const headers = fetchMock.mock.calls[0][1].headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer a-token");
  });

  it("sends no Authorization header when logged out", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {}));
    vi.stubGlobal("fetch", fetchMock);

    await api.get("/health");

    const headers = fetchMock.mock.calls[0][1].headers as Headers;
    expect(headers.has("Authorization")).toBe(false);
  });
});

describe("a 401", () => {
  it("ends the session when a token was sent", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(401, { detail: "expired" })));
    const expired = vi.fn();
    setSessionExpiredHandler(expired);
    writeToken("stale-token");

    await expect(api.get("/students")).rejects.toBeInstanceOf(ApiError);

    expect(expired).toHaveBeenCalledOnce();
    expect(readToken()).toBeNull();
  });

  it("leaves everything alone when no token was sent", async () => {
    // A failed login is a 401 too. Treating it as an expired session would
    // clear state that a logged-out user does not have, and - worse - fire a
    // "you have been signed out" redirect at someone who never signed in.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse(401, { detail: "Incorrect email or password" })),
    );
    const expired = vi.fn();
    setSessionExpiredHandler(expired);

    await expect(api.login("nobody@example.com", "wrong")).rejects.toThrow(
      "Incorrect email or password",
    );

    expect(expired).not.toHaveBeenCalled();
  });
});

describe("errors", () => {
  it("carries the sentence the API sent", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(409, { detail: "Payment of 60.00 exceeds the 55.00 still owed." }),
      ),
    );

    await expect(api.post("/payments", {})).rejects.toThrow(/55.00 still owed/);
  });

  it("keeps field errors addressable so a form can highlight the input", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(422, {
          detail: "amount: Input should be greater than 0",
          errors: [{ field: "amount", message: "Input should be greater than 0" }],
        }),
      ),
    );

    const error = (await api.post("/payments", {}).catch((caught) => caught)) as ApiError;
    expect(error.status).toBe(422);
    expect(error.fieldError("amount")).toBe("Input should be greater than 0");
    expect(error.fieldError("something_else")).toBeUndefined();
  });

  it("survives a response that is not our envelope at all", async () => {
    // A proxy or gateway between the browser and the API answers in HTML.
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<h1>502</h1>", { status: 502 })));

    const error = (await api.get("/students").catch((caught) => caught)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(502);
    expect(error.message).toContain("502");
  });
});

describe("login", () => {
  it("posts form encoding, because that is what the API's docs button uses", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { access_token: "t", token_type: "bearer", expires_in: 3600 }));
    vi.stubGlobal("fetch", fetchMock);

    await api.login("ama@example.com", "correct-horse");

    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers["Content-Type"]).toBe("application/x-www-form-urlencoded");
    expect(String(init.body)).toContain("username=ama%40example.com");
  });
});

describe("query", () => {
  it("leaves out anything unset rather than sending empty filters", () => {
    expect(query({ class_id: 3, status: undefined, q: "", limit: 50 })).toBe("?class_id=3&limit=50");
  });

  it("is empty when there is nothing to ask for", () => {
    expect(query({ q: undefined })).toBe("");
  });

  it("escapes what it is given", () => {
    expect(query({ q: "ama mensah & co" })).toContain("ama+mensah+%26+co");
  });
});
