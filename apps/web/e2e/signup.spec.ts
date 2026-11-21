import { expect, test } from "@playwright/test";
import { signup } from "./helpers";

test("a new user can sign up and reach the workspace dashboard", async ({ page }) => {
  const email = await signup(page);
  await expect(page.getByText(email, { exact: false }).first()).toBeVisible();
  await expect(page.getByText("No workspaces yet.")).toBeVisible();
});

test("registration rejects a weak password", async ({ page }) => {
  await page.goto("/register");
  await page.getByPlaceholder("you@company.com").fill("weak@example.com");
  await page.getByPlaceholder("••••••••").fill("short");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page).toHaveURL(/\/register$/);
});
