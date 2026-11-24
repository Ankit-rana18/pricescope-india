import { describe, expect, it } from "vitest";

import { lookupSchema } from "@/lib/validators";

const URL = "https://www.amazon.in/dp/B07JGFGW3V";

describe("lookupSchema", () => {
  it.each([
    ["560001", "560001"],
    [" 560 001 ", "560001"],
    ["560-001", "560001"],
  ])("normalises PIN %j to %j", (raw, expected) => {
    expect(lookupSchema.parse({ url: URL, pincode: raw }).pincode).toBe(expected);
  });

  it.each([
    ["", "Enter your 6-digit PIN code."],
    ["56001", "A PIN code is exactly 6 digits."],
    ["5600011", "A PIN code is exactly 6 digits."],
    ["56OO01", "A PIN code is exactly 6 digits."],
    ["५६०००१", "A PIN code is exactly 6 digits."],
    ["012345", "Indian PIN codes don't start with 0."],
  ])("rejects PIN %j", (raw, message) => {
    const result = lookupSchema.safeParse({ url: URL, pincode: raw });
    expect(result.success).toBe(false);
    expect(result.error?.issues[0]?.message).toBe(message);
  });

  it("requires a link and trims it", () => {
    expect(lookupSchema.safeParse({ url: "   ", pincode: "560001" }).success).toBe(false);
    expect(lookupSchema.parse({ url: `  ${URL}  `, pincode: "560001" }).url).toBe(URL);
  });
});
