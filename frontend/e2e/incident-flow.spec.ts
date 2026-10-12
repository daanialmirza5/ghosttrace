import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const repo = resolve(import.meta.dirname, "../..");
const python =
  process.env.GHOSTTRACE_PYTHON ??
  (process.platform === "win32" ? join(repo, "backend", ".venv", "Scripts", "python.exe") : join(repo, "backend", ".venv", "bin", "python"));

test("generate, import, investigate, replay and export an incident", async ({ page }) => {
  // 1. Generate a synthetic incident that is not one of the bundled datasets.
  const dir = mkdtempSync(join(tmpdir(), "ghosttrace-e2e-"));
  const file = join(dir, "cache-incident.jsonl");
  const truthFile = join(dir, "truth.json");
  execFileSync(python, [join(repo, "scripts", "generate_scenario.py"), "--scenario", "cache-failure", "--seed", "3001", "--vary", "--out", file, "--truth", truthFile]);
  const truth = JSON.parse(readFileSync(truthFile, "utf-8")) as { root_cause_service: string };

  // 2. Import it through the UI.
  await page.goto("/import");
  await page.getByTestId("file-input").setInputFiles(file);
  await page.getByRole("button", { name: "Validate and import" }).click();
  await expect(page.getByText("Import summary: cache-incident.jsonl")).toBeVisible();
  await expect(page.locator("dl").getByText("Completed", { exact: true })).toBeVisible();

  // 3. Open the reconstructed incident.
  await page.getByRole("link", { name: /incident(s)? detected/ }).click();
  await page.getByRole("link", { name: /affecting/ }).first().click();
  await expect(page.getByRole("heading", { name: "Ranked root-cause hypotheses" })).toBeVisible();
  await expect(page.locator("#hyp-1")).toHaveText(truth.root_cause_service);
  await expect(page.getByText("heuristic score (not a probability)").first()).toBeVisible();

  // 4. Inspect evidence behind a hypothesis.
  await page.locator("article").first().getByRole("button", { name: /^ev-/ }).first().click();
  const drawer = page.getByRole("dialog");
  await expect(drawer.getByText("Event evidence")).toBeVisible();
  await expect(drawer.getByText("Cited by")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();

  // 5. Timeline with a category filter.
  await page.getByRole("link", { name: "Timeline", exact: true }).last().click();
  const events = page.getByRole("list", { name: "Timeline events" });
  await expect(events.locator("li").first()).toBeVisible();
  await page.getByRole("button", { name: /^Timeout/ }).click();
  await expect(events.locator("li").first()).toContainText("timed out");

  // 6. Service graph built from the data.
  await page.getByRole("link", { name: "Service graph" }).last().click();
  await expect(page.getByTestId(`graph-node-${truth.root_cause_service}`)).toBeVisible();
  await page.getByTestId(`graph-node-${truth.root_cause_service}`).click();
  await expect(page.getByText("Latency samples")).toBeVisible();

  // 7. Deterministic replay controls.
  await page.getByRole("link", { name: "Replay", exact: true }).last().click();
  const position = page.getByTestId("replay-position");
  await expect(position).toContainText("Frame 1 /");
  await page.getByRole("button", { name: "Step forward" }).click();
  await expect(position).toContainText("Frame 2 /");
  await page.getByRole("button", { name: "Step backward" }).click();
  await expect(position).toContainText("Frame 1 /");
  await page.getByRole("button", { name: "Jump to end" }).click();
  await expect(page.getByTestId(`replay-status-${truth.root_cause_service}`)).toBeVisible();
  await page.getByRole("button", { name: "Jump to start" }).click();
  await page.getByRole("button", { name: "Play", exact: true }).click();
  await expect(position).not.toContainText("Frame 1 /");
  await page.getByRole("button", { name: "Pause", exact: true }).click();

  // 8. Export a Markdown report.
  await page.getByRole("link", { name: "Report", exact: true }).click();
  await page.getByRole("button", { name: "Generate report" }).click();
  await expect(page.getByTestId("report-preview")).toContainText("# Incident report:");
  await expect(page.getByTestId("report-preview")).toContainText(truth.root_cause_service);
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("link", { name: /Download Markdown/ }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^ghosttrace-inc_.*\.md$/);
});

test("navigation reaches every page without errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  for (const [path, heading] of [
    ["/", "Dashboard"],
    ["/import", "Import events"],
    ["/incidents", "Incidents"],
    ["/timeline", "Timeline"],
    ["/graph", "Service graph"],
    ["/replay", "Replay"],
    ["/compare", "Healthy vs failed comparison"],
    ["/reports", "Reports"],
    ["/settings", "Settings and local configuration"],
    ["/help", "Help and documentation"],
  ] as const) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
  }
  expect(errors).toEqual([]);
});
