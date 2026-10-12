import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ImportPage, parseCsvHeader } from "../features/ingestion/ImportPage";
import { importSummary } from "./fixtures";
import { mockApi, renderWithProviders } from "./utils";

const baseRoutes = {
  "GET /datasets/demo": [{ name: "cache-failure", title: "Slow product pages", summary: "Product pages slow down.", filename: "cache-failure.jsonl", format: "jsonl", size_bytes: 1024, field_mapping: null }],
  "GET /imports": { items: [], total: 0, limit: 10, offset: 0 },
};

test("parses quoted CSV headers", () => {
  expect(parseCsvHeader('time,"svc, name",level\r\n1,2,3')).toEqual(["time", "svc, name", "level"]);
  expect(parseCsvHeader('"a""b",c')).toEqual(['a"b', "c"]);
});

test("uploads a file and shows line-level validation errors", async () => {
  const { calls } = mockApi({ ...baseRoutes, "POST /imports": { status: 201, body: importSummary() } });
  renderWithProviders(<ImportPage />);
  const file = new File(['{"timestamp":1,"service":"a","severity":"info"}\n'], "events.jsonl", { type: "application/json" });
  await userEvent.upload(screen.getByTestId("file-input"), file);
  await userEvent.click(screen.getByRole("button", { name: "Validate and import" }));

  expect(await screen.findByText("Import summary: events.jsonl")).toBeInTheDocument();
  const errors = screen.getByRole("table", { name: "Validation errors" });
  expect(errors).toHaveTextContent("line 3");
  expect(errors).toHaveTextContent("unknown severity 'loud'");
  expect(screen.getByText(/Naive timestamp assumed utc: 1/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /1 incident detected/ })).toHaveAttribute("href", "/incidents?import_id=imp_1");

  const post = calls.find((call) => call.method === "POST")!;
  const form = post.init!.body as FormData;
  expect((form.get("file") as File).name).toBe("events.jsonl");
  expect(form.get("format")).toBe("auto");
  expect(form.get("field_mapping")).toBeNull();
});

test("CSV uploads send the chosen field mapping", async () => {
  const { calls } = mockApi({ ...baseRoutes, "POST /imports": { status: 201, body: importSummary({ format: "csv" }) } });
  renderWithProviders(<ImportPage />);
  const file = new File(["when,svc,lvl\n2026-03-14T09:00:00Z,api,info\n"], "events.csv", { type: "text/csv" });
  await userEvent.upload(screen.getByTestId("file-input"), file);
  await userEvent.selectOptions(await screen.findByLabelText("Map column when"), "timestamp");
  await userEvent.selectOptions(screen.getByLabelText("Map column svc"), "service");
  await userEvent.click(screen.getByRole("button", { name: "Validate and import" }));
  await waitFor(() => expect(calls.some((call) => call.method === "POST")).toBe(true));
  const form = calls.find((call) => call.method === "POST")!.init!.body as FormData;
  expect(JSON.parse(String(form.get("field_mapping")))).toEqual({ when: "timestamp", svc: "service" });
});

test("a rejected upload shows the server's error", async () => {
  mockApi({ ...baseRoutes, "POST /imports": { status: 413, body: { error: { code: "payload_too_large", message: "File exceeds the 10 MiB upload limit.", request_id: "r1" } } } });
  renderWithProviders(<ImportPage />);
  await userEvent.upload(screen.getByTestId("file-input"), new File(["x"], "big.jsonl"));
  await userEvent.click(screen.getByRole("button", { name: "Validate and import" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("File exceeds the 10 MiB upload limit.");
});

test("demo datasets can be imported with one click", async () => {
  const { calls } = mockApi({ ...baseRoutes, "POST /datasets/demo/:name/import": { status: 201, body: importSummary({ name: "Slow product pages", status: "completed", errors: [], rejected: 0 }) } });
  renderWithProviders(<ImportPage />);
  await userEvent.click(await screen.findByRole("button", { name: "Import Slow product pages" }));
  expect(await screen.findByText("Import summary: Slow product pages")).toBeInTheDocument();
  expect(calls.some((call) => call.url.pathname === "/api/v1/datasets/demo/cache-failure/import")).toBe(true);
});
