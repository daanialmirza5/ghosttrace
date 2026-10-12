import { vi } from "vitest";

import { ApiError, api } from "../services/api";
import { mockApi } from "./utils";

test("structured API errors become ApiError with code and request ID", async () => {
  mockApi({ "GET /imports/:id": { status: 404, body: { error: { code: "not_found", message: "Import 'x' was not found.", request_id: "abc" } } } });
  const error = await api.getImport("x").catch((e: unknown) => e);
  expect(error).toBeInstanceOf(ApiError);
  expect(error).toMatchObject({ status: 404, code: "not_found", requestId: "abc", message: "Import 'x' was not found." });
});

test("network failures are reported clearly", async () => {
  vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
  await expect(api.health()).rejects.toMatchObject({ code: "network_error" });
});

test("query parameters skip empty values and repeat arrays", async () => {
  const { calls } = mockApi({ "GET /incidents/:id/timeline": { items: [] } });
  await api.getTimeline("inc_1", { service: ["a", "b"], severity: undefined, q: "", limit: 5 });
  expect(calls[0]!.url.search).toBe("?service=a&service=b&limit=5");
});

test("ids are URL-encoded", async () => {
  const { calls } = mockApi({ "GET /incidents/:id/events/:event": { event: {} } });
  await api.getIncidentEvent("inc_1", "ev/../x");
  expect(calls[0]!.url.pathname).toBe("/api/v1/incidents/inc_1/events/ev%2F..%2Fx");
});
