import { expect, test } from "@playwright/test";
import { createWorkspace, signup, uploadText } from "./helpers";

test("a document can be uploaded and becomes ready", async ({ page }) => {
  await signup(page);
  await createWorkspace(page, "E2E Uploads");

  const filename = "e2e-notes.txt";
  await uploadText(
    page,
    filename,
    "grounding test: the capital of france is paris",
  );

  // Queued -> indexing -> ready is driven by the ingestion worker.
  await expect(page.getByText("ready", { exact: true })).toBeVisible({
    timeout: 60_000,
  });

  const row = page.locator("div.border-b", { hasText: filename }).last();
  await expect(row).toContainText("ready");
});

test("uploaded files are scoped to the workspace", async ({ page }) => {
  await signup(page);
  await createWorkspace(page, "E2E Tenant A");
  await uploadText(page, "only-in-a.txt", "alpha content");

  await page.goto("/dashboard");
  await createWorkspace(page, "E2E Tenant B");
  await expect(page.getByText("only-in-a.txt")).toHaveCount(0);
});
