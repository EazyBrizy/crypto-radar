import { expect, test } from "@playwright/test";

test("renders the Crypto Radar shell", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByText("Crypto Radar").first()).toBeVisible();
  await expect(page.getByRole("button", { name: /Radar/i })).toBeVisible();
  await expect(page.getByText(/Realtime:/i)).toBeVisible();
});
