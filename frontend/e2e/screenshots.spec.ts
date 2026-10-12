import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join, resolve } from "node:path";

// Captures documentation screenshots from the running application (npm run screenshots).
const out = resolve(import.meta.dirname, "../../docs/screenshots");
mkdirSync(out, { recursive: true });

async function shot(page: Page, name: string) {
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(600);
  await page.screenshot({ path: join(out, `${name}.png`), fullPage: false });
}

test("@screenshots capture the main views", async ({ page, request }) => {
  for (const name of ["healthy-control", "faulty-deployment", "cache-failure", "ambiguous-partition"]) {
    const response = await request.post(`/api/v1/datasets/demo/${name}/import`);
    expect(response.ok()).toBeTruthy();
  }
  const incidents = await (await request.get("/api/v1/incidents?limit=50")).json();
  const cache = incidents.items.find((item: { import_name: string }) => item.import_name.startsWith("Slow product pages"));
  const ambiguous = incidents.items.find((item: { evidence_status: string }) => item.evidence_status === "insufficient");

  await page.goto("/");
  await expect(page.getByText("Recent incidents")).toBeVisible();
  await shot(page, "dashboard");

  await page.goto("/import");
  await page.getByRole("button", { name: "Import Malformed records sample" }).click();
  await expect(page.getByLabel("Validation errors")).toBeVisible();
  await shot(page, "import");

  await page.goto(`/incidents/${cache.id}`);
  await expect(page.locator("#hyp-1")).toBeVisible();
  await shot(page, "incident-hypotheses");

  await page.locator("article").first().getByRole("button", { name: /^ev-/ }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await shot(page, "evidence-drawer");
  await page.keyboard.press("Escape");

  await page.goto(`/incidents/${cache.id}/timeline`);
  await expect(page.getByRole("list", { name: "Timeline events" })).toBeVisible();
  await shot(page, "timeline");

  await page.goto(`/incidents/${cache.id}/graph`);
  await page.getByTestId("graph-node-redis-cache").click();
  await shot(page, "service-graph");

  await page.goto(`/incidents/${cache.id}/replay`);
  await expect(page.getByTestId("replay-position")).toBeVisible();
  await page.getByLabel("Replay position").fill("420");
  await shot(page, "replay");

  await page.goto("/compare");
  await page.getByRole("button", { name: "Compare executions" }).click();
  await expect(page.getByText("Notable differences")).toBeVisible();
  await shot(page, "comparison");

  await page.goto(`/incidents/${cache.id}/report`);
  await page.getByRole("button", { name: "Generate report" }).click();
  await expect(page.getByTestId("report-preview")).toBeVisible();
  await shot(page, "report");

  await page.goto(`/incidents/${ambiguous.id}`);
  await expect(page.getByText("Insufficient evidence").first()).toBeVisible();
  await shot(page, "insufficient-evidence");
});
