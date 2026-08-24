import { describe, expect, it } from "vitest";

import { formatMoney, fromMinorUnits, toMinorUnits, validateAmount } from "./money";

describe("toMinorUnits", () => {
  it.each([
    ["250.00", 25000],
    ["0.01", 1],
    ["99.90", 9990],
    ["7", 700],
    ["1234.56", 123456],
  ])("reads %s as %i cents", (amount, expected) => {
    expect(toMinorUnits(amount)).toBe(expected);
  });

  it("does not go through a float on the way", () => {
    // 1.15 * 100 is 114.99999999999999 in IEEE 754, and Math.round hides it
    // until the day it does not.
    expect(toMinorUnits("1.15")).toBe(115);
    expect(toMinorUnits("8.20")).toBe(820);
    expect(toMinorUnits("0.29")).toBe(29);
  });

  it.each(["", "abc", "1.234", "1.2.3", "12,00", "1e3", " "])(
    "refuses %o rather than guessing",
    (bad) => {
      expect(toMinorUnits(bad)).toBeNull();
    },
  );
});

describe("fromMinorUnits", () => {
  it.each([
    [25000, "250.00"],
    [1, "0.01"],
    [9990, "99.90"],
    [0, "0.00"],
  ])("writes %i cents as %s", (minor, expected) => {
    expect(fromMinorUnits(minor)).toBe(expected);
  });

  it("round-trips whatever the API sends", () => {
    for (const amount of ["250.00", "0.01", "99.90", "1234.56"]) {
      expect(fromMinorUnits(toMinorUnits(amount)!)).toBe(amount);
    }
  });
});

describe("formatMoney", () => {
  it("renders two decimal places", () => {
    expect(formatMoney("250.00")).toContain("250.00");
    expect(formatMoney("0.05")).toContain("0.05");
  });

  it("keeps the cents on a whole amount", () => {
    expect(formatMoney("7")).toContain("7.00");
  });

  it("does not throw on something unexpected", () => {
    // A malformed amount is a bug worth logging, not worth a blank screen in
    // front of a parent trying to pay.
    expect(() => formatMoney("nonsense")).not.toThrow();
  });
});

describe("validateAmount", () => {
  it("accepts a partial payment", () => {
    expect(validateAmount("50.00", "250.00")).toBeNull();
  });

  it("accepts exactly what is owed", () => {
    expect(validateAmount("250.00", "250.00")).toBeNull();
  });

  it("refuses a cent more than is owed", () => {
    expect(validateAmount("250.01", "250.00")).toMatch(/more than/);
  });

  it.each(["0", "0.00", "-5.00"])("refuses %s", (amount) => {
    expect(validateAmount(amount, "250.00")).toBeTruthy();
  });

  it("refuses an empty box without shouting about format", () => {
    expect(validateAmount("", "250.00")).toBe("Enter an amount.");
  });

  it("refuses three decimal places, as the API does", () => {
    expect(validateAmount("10.005", "250.00")).toMatch(/like 25.00/);
  });

  it("names the amount still owed so the payer can fix it", () => {
    expect(validateAmount("999.00", "55.00")).toContain("55.00");
  });
});
