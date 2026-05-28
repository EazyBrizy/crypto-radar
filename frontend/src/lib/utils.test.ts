import { describe, expect, it } from "vitest";

import { cn } from "./utils";

describe("cn", () => {
  it("merges Tailwind classes with later values winning", () => {
    expect(cn("px-2 text-sm", false && "hidden", "px-4")).toContain("px-4");
  });
});
