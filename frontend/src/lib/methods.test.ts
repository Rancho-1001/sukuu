import { describe, expect, it } from "vitest";

import { describeMethods, methodLabel } from "./methods";

describe("describeMethods", () => {
  it("reads as a sentence fragment", () => {
    expect(describeMethods(["mobile_money", "card", "bank"])).toBe("mobile money, card or bank");
  });
  it("handles one", () => {
    expect(describeMethods(["card"])).toBe("card");
  });
  it("handles two without a comma", () => {
    expect(describeMethods(["mobile_money", "card"])).toBe("mobile money or card");
  });
  it("handles none", () => {
    expect(describeMethods([])).toBe("");
  });
});

describe("methodLabel", () => {
  it("says mobile money, not mobile_money", () => {
    expect(methodLabel("mobile_money")).toBe("Mobile money");
  });
});
