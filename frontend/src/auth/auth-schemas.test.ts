import { describe, expect, it } from "vitest";

import { AuthSessionSchema, LoginFormSchema } from "./auth-schemas";
import { demoAuthSession } from "./auth-config";

describe("auth schemas", () => {
  it("accepts the demo session contract", () => {
    expect(AuthSessionSchema.parse(demoAuthSession).user.id).toBe("demo_user");
  });

  it("rejects weak login credentials", () => {
    expect(() => LoginFormSchema.parse({ email: "bad", password: "short" })).toThrow();
  });
});
