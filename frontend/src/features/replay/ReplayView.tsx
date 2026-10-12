import { Pause, Play, SkipBack, SkipForward, StepBack, StepForward } from "lucide-react";
import { useEffect, useMemo, useState, type KeyboardEvent } from "react";

import { EventChip } from "../../components/EventInspector";
import { Badge, Button, Card, EmptyState, ErrorState, Loading, SeverityBadge, StatusDot, cx } from "../../components/ui";
import { useIncidentGraph, useReplay } from "../../hooks/queries";
import { formatTime, humanize } from "../../lib/format";
import type { GraphResponse, IncidentDetail, ReplayRequest, ReplayResponse, Severity, TimelineCategory } from "../../types/api";
import { ServiceGraph } from "../dependency-graph/ServiceGraph";
import { CATEGORY_TONE } from "../timeline/TimelineView";
import { ReplayStateIndex, playbackDelay } from "./replayState";

const SPEEDS = [1, 5, 10, 30, 60] as const;

export function useReplayPlayer(replay: ReplayResponse | undefined) {
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<number>(10);
  const count = replay?.frame_count ?? 0;

  // The player is remounted (keyed by replay_id) for every new replay, so no reset effect.
  useEffect(() => {
    if (!playing || !replay || index >= count - 1) return;
    const timer = window.setTimeout(() => {
      const next = Math.min(count - 1, index + 1);
      setIndex(next);
      if (next >= count - 1) setPlaying(false);
    }, playbackDelay(replay, index, speed));
    return () => window.clearTimeout(timer);
  }, [playing, index, speed, replay, count]);

  return {
    index,
    playing,
    speed,
    setSpeed,
    play: () => {
      if (index >= count - 1) setIndex(0);
      setPlaying(true);
    },
    pause: () => setPlaying(false),
    toggle: () => setPlaying((p) => !p && count > 0),
    step: (delta: number) => {
      setPlaying(false);
      setIndex((i) => Math.max(0, Math.min(count - 1, i + delta)));
    },
    jump: (to: number) => {
      setPlaying(false);
      setIndex(Math.max(0, Math.min(count - 1, to)));
    },
  };
}

function Filters({ incident, onBuild, loading }: { incident: IncidentDetail; onBuild: (body: ReplayRequest) => void; loading: boolean }) {
  const [service, setService] = useState("");
  const [severity, setSeverity] = useState("");
  const [category, setCategory] = useState("");
  return (
    <form
      className="flex flex-wrap items-end gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        onBuild({
          services: service ? [service] : [],
          severities: severity ? [severity as Severity] : [],
          categories: category ? [category as TimelineCategory] : [],
        });
      }}
    >
      <label className="text-xs text-slate-600">
        Service
        <select className="input mt-1 w-44 py-1" value={service} onChange={(e) => setService(e.target.value)}>
          <option value="">All</option>
          {incident.services.map((name) => (
            <option key={name}>{name}</option>
          ))}
        </select>
      </label>
      <label className="text-xs text-slate-600">
        Severity
        <select className="input mt-1 w-32 py-1" value={severity} onChange={(e) => setSeverity(e.target.value)}>
          <option value="">All</option>
          {["critical", "error", "warning", "info"].map((name) => (
            <option key={name}>{name}</option>
          ))}
        </select>
      </label>
      <label className="text-xs text-slate-600">
        Category
        <select className="input mt-1 w-40 py-1" value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">All</option>
          {Object.keys(CATEGORY_TONE).map((name) => (
            <option key={name} value={name}>
              {humanize(name)}
            </option>
          ))}
        </select>
      </label>
      <Button type="submit" variant="primary" loading={loading}>
        Build replay
      </Button>
    </form>
  );
}

export function ReplayView({ incident }: { incident: IncidentDetail }) {
  const replay = useReplay(incident.id);
  const graph = useIncidentGraph(incident.id);
  const data = replay.data;

  useEffect(() => {
    if (!replay.data && !replay.isPending && !replay.error) replay.mutate({});
    // Build the unfiltered replay once on first view.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="space-y-4">
      <Card title="Replay settings">
        <Filters incident={incident} onBuild={(body) => replay.mutate(body)} loading={replay.isPending} />
        <p className="mt-2 text-xs text-slate-500">
          Frames are the incident window's real events in timestamp order. Filters hide events from playback but service health is always computed from every event (30-second window),
          so the graph state at a shown event is identical with or without filters.
        </p>
      </Card>
      {replay.error && <ErrorState error={replay.error} />}
      {replay.isPending && !data && <Loading label="Building replay…" />}
      {data && data.frame_count === 0 && <Card><EmptyState title="No events match these replay filters" /></Card>}
      {data && data.frame_count > 0 && <ReplayPlayer key={data.replay_id} data={data} graph={graph.data} graphError={graph.error} />}
    </div>
  );
}

function ReplayPlayer({ data, graph, graphError }: { data: ReplayResponse; graph: GraphResponse | undefined; graphError: unknown }) {
  const player = useReplayPlayer(data);
  const stateIndex = useMemo(() => new ReplayStateIndex(data), [data]);
  const state = stateIndex.stateAt(player.index);
  const frame = data.frames[player.index];

  const onKeyDown = (event: KeyboardEvent) => {
    if ((event.target as HTMLElement).tagName === "SELECT" || (event.target as HTMLElement).tagName === "INPUT") return;
    if (event.key === " ") {
      event.preventDefault();
      player.toggle();
    } else if (event.key === "ArrowRight") player.step(event.shiftKey ? 10 : 1);
    else if (event.key === "ArrowLeft") player.step(event.shiftKey ? -10 : -1);
    else if (event.key === "Home") player.jump(0);
    else if (event.key === "End") player.jump(data.frame_count - 1);
  };

  const windowStart = Math.max(0, player.index - 6);
  const visibleFrames = data.frames.slice(windowStart, windowStart + 14);

  if (!frame) return null;
  return (
    <div className="space-y-4" onKeyDown={onKeyDown}>
        <>
          <Card padded={false}>
            <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 p-3" role="toolbar" aria-label="Replay controls" tabIndex={0}>
              <Button size="sm" variant="ghost" onClick={() => player.jump(0)} aria-label="Jump to start">
                <SkipBack className="h-4 w-4" />
              </Button>
              <Button size="sm" variant="ghost" onClick={() => player.step(-1)} aria-label="Step backward" disabled={player.index === 0}>
                <StepBack className="h-4 w-4" />
              </Button>
              {player.playing ? (
                <Button size="sm" variant="primary" onClick={player.pause} aria-label="Pause">
                  <Pause className="h-4 w-4" /> Pause
                </Button>
              ) : (
                <Button size="sm" variant="primary" onClick={player.play} aria-label="Play">
                  <Play className="h-4 w-4" /> Play
                </Button>
              )}
              <Button size="sm" variant="ghost" onClick={() => player.step(1)} aria-label="Step forward" disabled={player.index >= data.frame_count - 1}>
                <StepForward className="h-4 w-4" />
              </Button>
              <Button size="sm" variant="ghost" onClick={() => player.jump(data.frame_count - 1)} aria-label="Jump to end">
                <SkipForward className="h-4 w-4" />
              </Button>
              <label className="ml-2 flex items-center gap-2 text-xs text-slate-600">
                Speed
                <select aria-label="Playback speed" className="input w-20 py-1" value={player.speed} onChange={(e) => player.setSpeed(Number(e.target.value))}>
                  {SPEEDS.map((speed) => (
                    <option key={speed} value={speed}>
                      {speed}×
                    </option>
                  ))}
                </select>
              </label>
              <span className="ml-auto font-mono text-xs text-slate-600" aria-live="polite" data-testid="replay-position">
                Frame {player.index + 1} / {data.frame_count} · {formatTime(frame.timestamp)} UTC
              </span>
            </div>
            <div className="px-4 py-3">
              <input
                type="range"
                min={0}
                max={data.frame_count - 1}
                value={player.index}
                onChange={(e) => player.jump(Number(e.target.value))}
                className="w-full accent-accent-600"
                aria-label="Replay position"
              />
              <p className="text-[11px] text-slate-400">
                Space play/pause · ←/→ step (Shift ×10) · Home/End. Idle gaps longer than 1.5 s of playback are compressed.
              </p>
            </div>
          </Card>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
            <div>
              {graph ? (
                <ServiceGraph nodes={graph.nodes} edges={graph.edges} statusOverride={state.statuses} activeEdge={frame.edge} selectedId={frame.service} height={460} />
              ) : graphError ? (
                <ErrorState error={graphError} />
              ) : (
                <Loading />
              )}
              <div className="mt-3 flex flex-wrap gap-3">
                {Object.entries(state.statuses).map(([service, status]) => (
                  <span key={service} className="flex items-center gap-1 text-xs" data-testid={`replay-status-${service}`} data-status={status}>
                    <StatusDot status={status} label={false} />
                    {service}
                    {state.errorTotals[service] ? <span className="text-red-600">({state.errorTotals[service]} err)</span> : null}
                  </span>
                ))}
              </div>
            </div>
            <Card title="Current event" padded={false}>
              <div className="space-y-2 border-b border-slate-100 p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <SeverityBadge severity={frame.severity} />
                  <Badge tone={CATEGORY_TONE[frame.category]}>{humanize(frame.category)}</Badge>
                  <span className="text-xs font-medium">{frame.service}</span>
                  {frame.target_service && <span className="text-xs text-slate-500">→ {frame.target_service}</span>}
                </div>
                <p className="text-sm text-slate-800">{frame.message}</p>
                <EventChip id={frame.event_id} />
              </div>
              <ol className="max-h-80 overflow-y-auto" aria-label="Nearby frames">
                {visibleFrames.map((item) => (
                  <li key={item.index}>
                    <button
                      type="button"
                      onClick={() => player.jump(item.index)}
                      className={cx("flex w-full items-center gap-2 px-4 py-1.5 text-left text-xs hover:bg-slate-50", item.index === player.index && "bg-accent-50")}
                      aria-current={item.index === player.index ? "step" : undefined}
                    >
                      <span className="w-20 flex-none font-mono text-slate-500">{formatTime(item.timestamp)}</span>
                      <span className={cx("h-1.5 w-1.5 flex-none rounded-full", item.severity === "error" || item.severity === "critical" ? "bg-red-500" : item.severity === "warning" ? "bg-amber-500" : "bg-slate-300")} />
                      <span className="w-28 flex-none truncate">{item.service}</span>
                      <span className="truncate text-slate-500">{item.message}</span>
                    </button>
                  </li>
                ))}
              </ol>
            </Card>
          </div>
        </>
    </div>
  );
}
