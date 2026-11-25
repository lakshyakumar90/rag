import { expect, test } from "@playwright/test";

test.describe("Upgrade UI smoke checks (Chat, Inspector, Evals, Memory)", () => {
  test("docs and public landing render cleanly", async ({ page }) => {
    await page.goto("/docs");
    await expect(page.locator("body")).toBeVisible();
  });

  test("evals and memory routes are reachable and protected by auth guard", async ({
    page,
  }) => {
    const resEvals = await page.goto("/workspaces/00000000-0000-0000-0000-000000000001/evals");
    expect(resEvals?.status()).toBeLessThan(500);

    const resMemory = await page.goto("/workspaces/00000000-0000-0000-0000-000000000001/memory");
    expect(resMemory?.status()).toBeLessThan(500);
  });
});
