import { expect, test } from "@playwright/test";
import { createWorkspace, signup } from "./helpers";

test("Ctrl+K opens one workspace search panel and the composer fits 320px", async ({
  page,
}) => {
  await signup(page);
  await createWorkspace(page, "E2E Layout");
  await page.locator('aside a[href$="/chat"]').click();
  await expect(page).toHaveURL(/\/chat$/);

  await page.keyboard.press("Control+k");
  const dialogs = page.getByRole("dialog");
  await expect(dialogs).toHaveCount(1);
  await expect(page.getByLabel("Search workspace documents and pages")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialogs).toHaveCount(0);

  await page.setViewportSize({ width: 320, height: 700 });
  await expect(page.getByLabel("Question")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send" })).toBeVisible();
  await expect(page.getByLabel("Provider for next message")).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
});
