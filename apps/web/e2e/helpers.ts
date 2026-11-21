import { expect, type Page } from "@playwright/test";

/** Sign up through the UI (registration also logs the user in). */
export async function signup(page: Page): Promise<string> {
  const email = `e2e-${Date.now()}-${Math.random().toString(36).slice(2, 7)}@example.com`;
  await page.goto("/register");
  await page.getByPlaceholder("you@company.com").fill(email);
  await page.getByPlaceholder("••••••••").fill("StrongPassw0rd!");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("heading", { name: "Your workspaces" })).toBeVisible();
  return email;
}

/** Create a workspace from the dashboard and open its documents page. */
export async function createWorkspace(page: Page, name: string): Promise<void> {
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  await page.getByLabel("Workspace name").fill(name);
  await page.getByLabel("Workspace slug").fill(slug);
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page.getByText(name, { exact: true }).first()).toBeVisible();
  await page.getByRole("link").filter({ hasText: name }).first().click();
  await expect(page).toHaveURL(/\/documents$/);
}

/** Upload a text file through the hidden file input on the documents page. */
export async function uploadText(
  page: Page,
  filename: string,
  body: string,
): Promise<void> {
  await page.locator('input[type="file"]').setInputFiles({
    name: filename,
    mimeType: "text/plain",
    buffer: Buffer.from(body),
  });
  await expect(page.getByText(filename, { exact: true })).toBeVisible();
}
