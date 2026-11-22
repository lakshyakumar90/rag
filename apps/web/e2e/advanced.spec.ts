import { expect, test } from "@playwright/test";
import { createWorkspace, signup } from "./helpers";

test("advanced controls are present and reachable", async ({ page }) => {
  await signup(page);
  await createWorkspace(page, "E2E Advanced");
  await page.locator('aside a[href$="/documents"]').click();
  await expect(page.getByLabel("Source type")).toBeVisible();

  await page.locator('aside a[href$="/settings"]').click();
  await expect(page.getByRole("tab", { name: "Embeddings" })).toBeVisible();
  await page.getByRole("tab", { name: "AI providers" }).click();
  await expect(page.getByRole("button", { name: "Test connection" }).first()).toBeVisible();

  await page.locator('aside a[href$="/chat"]').click();
  await expect(page.getByLabel("Toggle agent mode")).toBeVisible();
});
