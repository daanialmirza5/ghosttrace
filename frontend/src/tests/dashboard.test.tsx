import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { DashboardPage } from "../features/dashboard/DashboardPage";
import { dashboard } from "./fixtures";
import { mockApi, renderWithProviders } from "./utils";

test("shows values returned by the backend", async () => {
  mockApi({ "GET /dashboard/summary": dashboard() });
  renderWithProviders(<DashboardPage />);
  expect(await screen.findByText("4,524")).toBeInTheDocument();
  expect(screen.getByText("9 records rejected during validation")).toBeInTheDocument();
  expect(screen.getByText("57 ms")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Latency increase and error spike affecting 6 services" })).toHaveAttribute("href", "/incidents/inc_1");
});

test("shows an empty state before anything is imported", async () => {
  mockApi({ "GET /dashboard/summary": dashboard({ import_count: 0, recent_incidents: [], recent_imports: [] }) });
  renderWithProviders(<DashboardPage />);
  expect(await screen.findByText("No data imported yet")).toBeInTheDocument();
});

test("API failures show the message, request ID and a working retry", async () => {
  let attempts = 0;
  mockApi({
    "GET /dashboard/summary": () => {
      attempts += 1;
      return attempts === 1
        ? { status: 503, body: { error: { code: "unavailable", message: "Database unavailable.", request_id: "req123" } } }
        : { body: dashboard() };
    },
  });
  renderWithProviders(<DashboardPage />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Database unavailable.");
  expect(screen.getByText("req123")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText("4,524")).toBeInTheDocument();
});
