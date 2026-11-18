import { describe, expect, it } from "vitest";
import { formatDate, formatINR } from "./format";

describe("format", () => {
  it("formats dates like 30 Oct 2026", () => {
    expect(formatDate("2026-10-30")).toBe("30 Oct 2026");
  });
  it("formats currency in INR", () => {
    expect(formatINR(150000)).toBe("₹1,50,000");
  });
});
