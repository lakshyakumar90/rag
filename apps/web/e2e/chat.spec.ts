import { expect, test } from "@playwright/test";
import { createWorkspace, signup, uploadText } from "./helpers";

test("a question produces an assistant answer with a conversation", async ({
  page,
}) => {
  await signup(page);
  await createWorkspace(page, "E2E Chat");
  await uploadText(page, "facts.txt", "the e2e secret word is cobalt");
  await expect(page.getByText("ready", { exact: true })).toBeVisible({
    timeout: 60_000,
  });

  await page.locator('aside a[href$="/chat"]').click();
  await expect(page).toHaveURL(/\/chat$/);

  const question = "What is the e2e secret word?";
  await page.getByLabel("Question").fill(question);
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.getByText(question, { exact: true })).toBeVisible();
  // With no provider configured the backend may answer "I don't know", but a
  // grounded pipeline still produces an assistant turn.
  await expect(page.locator("article").last()).toBeVisible();
  await expect(page.locator("article").last()).not.toBeEmpty();

  await expect
    .poll(async () => page.locator("article").count(), { timeout: 15_000 })
    .toBeGreaterThanOrEqual(2);
});

test("feedback can be submitted on an assistant answer", async ({ page }) => {
  await signup(page);
  await createWorkspace(page, "E2E Feedback");
  await uploadText(page, "guide.txt", "feedback test content");
  await expect(page.getByText("ready", { exact: true })).toBeVisible({
    timeout: 60_000,
  });

  await page.getByRole("link", { name: "Chat" }).first().click();
  await page.getByLabel("Question").fill("What does the guide say?");
  await page.getByRole("button", { name: "Send" }).click();

  // Feedback controls appear once the answer has a persisted id, so reload
  // the thread to load the assistant message from the server.
  await expect(page.locator("article").last()).not.toBeEmpty();
  await page.reload();
  await expect
    .poll(async () => page.getByRole("button", { name: "Good answer" }).count(), {
      timeout: 20_000,
    })
    .toBeGreaterThan(0);
  await page.getByRole("button", { name: "Good answer" }).first().click();
  await expect(page.getByText("Thanks for the feedback")).toBeVisible();
});
