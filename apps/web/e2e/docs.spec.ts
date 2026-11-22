import { expect, test } from "@playwright/test";

test("documentation and floorplan work without a session or API", async ({ page }) => {
  const apiCalls: string[] = [];
  await page.route("**/api/v1/**", async (route) => {
    apiCalls.push(route.request().url());
    await route.abort();
  });

  const response = await page.goto("/docs");
  expect(response?.status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Introduction", exact: true })).toBeVisible();

  await page.keyboard.press("Control+k");
  const search = page.getByRole("dialog", { name: "Search documentation" });
  await search.getByRole("textbox", { name: "Search pages" }).fill("system architecture");
  await search.getByRole("link", { name: /System architecture/ }).click();
  await expect(page).toHaveURL(/\/docs\/architecture$/);
  await page.getByRole("navigation", { name: "On this page" }).getByRole("link", { name: "Ingestion sequence" }).click();
  await expect(page).toHaveURL(/#ingestion-sequence$/);

  await page.setViewportSize({ width: 320, height: 720 });
  await page.getByText("Browse documentation").click();
  await page.getByRole("navigation", { name: "Documentation", exact: true }).getByRole("link", { name: "Interactive floorplan" }).click();
  await expect(page).toHaveURL(/\/docs\/floorplan$/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);

  await page.getByRole("link", { name: "Full screen" }).click();
  await expect(page).toHaveURL(/\/floorplan$/);
  const map = page.frameLocator('iframe[title="RAG architecture floorplan"]');
  await expect(map.locator("#svg")).toBeVisible();
  await page.setViewportSize({ width: 1440, height: 900 });
  await map.locator("#flows-btn").click();
  await expect(map.locator("#flowmenu").getByText("Index a source", { exact: true })).toBeVisible();
  expect(apiCalls).toEqual([]);
});
