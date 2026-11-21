import { expect, test } from "@playwright/test";

test("demo story is legible end to end", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("consent-checkbox").check();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/radar$/);

  // Integration proof: real agent flows render, including a pinned one.
  await expect(page.getByTestId("flow-count")).toContainText("34 of 34", { timeout: 45_000 });
  await expect(page.locator("[data-pinned]").first()).toBeVisible();
  await expect(page.getByTestId("gauge")).toContainText("804", { timeout: 15_000 });

  // No raw demo identifiers ever reach the page.
  const html = await page.content();
  for (const raw of ["hermione.demo@azkaban.test", "9876500042", "6f1c2a9e-4b7d-4e21-9c3a-5d8e7f0a1b2c", "12.971599"]) {
    expect(html).not.toContain(raw);
  }

  await page.getByRole("link", { name: "Insights" }).click();
  await expect(page.getByTestId("canary-hero")).toContainText("Dobby");
  await expect(page.getByTestId("insight-hashed_pii").first()).toContainText("SHA256");
  await expect(page.getByTestId("insight-cross_app").first()).toBeVisible();

  await page.getByRole("link", { name: "Patronus" }).click();
  await page.getByTestId("apply-blocklist-actions").click();
  await expect(page.getByTestId("recheck-panel")).toContainText("29 → 0", { timeout: 30_000 });
});
