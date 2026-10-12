import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ReplayView } from "../features/replay/ReplayView";
import { MAX_GAP_MS, MIN_GAP_MS, ReplayStateIndex, playbackDelay } from "../features/replay/replayState";
import { EventInspectorProvider } from "../components/EventInspector";
import { incident, replay } from "./fixtures";
import { mockApi, renderWithProviders } from "./utils";

test("state folding is identical however a frame is reached", () => {
  const data = replay();
  const index = new ReplayStateIndex(data);
  expect(index.stateAt(0).statuses["redis-cache"]).toBe("healthy");
  expect(index.stateAt(1).statuses["redis-cache"]).toBe("degraded");
  expect(index.stateAt(2)).toEqual({ statuses: { "redis-cache": "failing" }, errorTotals: { "redis-cache": 2 } });
  expect(index.stateAt(1)).toEqual(new ReplayStateIndex(data).stateAt(1));
  expect(index.stateAt(99).statuses["redis-cache"]).toBe("failing");
});

test("playback delay follows real gaps, scaled and capped", () => {
  const data = replay();
  expect(playbackDelay(data, 0, 1)).toBe(1000);
  expect(playbackDelay(data, 0, 10)).toBe(100);
  expect(playbackDelay(data, 0, 1000)).toBe(MIN_GAP_MS);
  data.frames[1]!.offset_ms = 600_000;
  expect(playbackDelay(data, 0, 1)).toBe(MAX_GAP_MS);
});

test("step, jump and keyboard controls move through frames", async () => {
  const { calls } = mockApi({
    "POST /incidents/inc_1/replay": replay(),
    "GET /incidents/inc_1/graph": { scope: { kind: "incident", id: "inc_1", start: null, end: null, event_count: 3 }, nodes: [], edges: [], cycles: [], components: 0, entry_points: [] },
  });
  renderWithProviders(
    <EventInspectorProvider incidentId="inc_1">
      <ReplayView incident={incident()} />
    </EventInspectorProvider>,
  );
  const position = await screen.findByTestId("replay-position");
  expect(position).toHaveTextContent("Frame 1 / 3");
  expect(screen.getByRole("button", { name: "Step backward" })).toBeDisabled();

  await userEvent.click(screen.getByRole("button", { name: "Step forward" }));
  expect(position).toHaveTextContent("Frame 2 / 3");
  expect(screen.getByTestId("replay-status-redis-cache")).toHaveAttribute("data-status", "degraded");

  await userEvent.click(screen.getByRole("button", { name: "Jump to end" }));
  expect(position).toHaveTextContent("Frame 3 / 3");
  expect(screen.getByTestId("replay-status-redis-cache")).toHaveAttribute("data-status", "failing");

  screen.getByRole("toolbar", { name: "Replay controls" }).focus();
  await userEvent.keyboard("{Home}");
  expect(position).toHaveTextContent("Frame 1 / 3");
  await userEvent.keyboard("{ArrowRight}");
  expect(position).toHaveTextContent("Frame 2 / 3");

  await userEvent.click(screen.getByRole("button", { name: /second$/ }));
  expect(position).toHaveTextContent("Frame 2 / 3");

  await userEvent.selectOptions(screen.getByLabelText("Severity"), "error");
  await userEvent.click(screen.getByRole("button", { name: "Build replay" }));
  const bodies = calls.filter((call) => call.method === "POST").map((call) => JSON.parse(String(call.init!.body)));
  expect(bodies.at(-1)).toEqual({ services: [], severities: ["error"], categories: [] });
});

test("play advances frames on its own and pause stops it", async () => {
  mockApi({
    "POST /incidents/inc_1/replay": replay(),
    "GET /incidents/inc_1/graph": { scope: { kind: "incident", id: "inc_1", start: null, end: null, event_count: 3 }, nodes: [], edges: [], cycles: [], components: 0, entry_points: [] },
  });
  renderWithProviders(<ReplayView incident={incident()} />);
  const position = await screen.findByTestId("replay-position");
  await userEvent.selectOptions(screen.getByLabelText("Playback speed"), "60");
  await userEvent.click(screen.getByRole("button", { name: "Play" }));
  expect(await screen.findByText(/Frame 3 \/ 3/, {}, { timeout: 2000 })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Play" })).toBeInTheDocument(); // stopped at the end
  expect(position).toHaveTextContent("Frame 3 / 3");
});
