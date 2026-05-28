import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Button } from "./button";

describe("Button", () => {
  it("renders and handles clicks", async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();

    render(<Button onClick={onClick}>Refresh</Button>);
    await user.click(screen.getByRole("button", { name: "Refresh" }));

    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
