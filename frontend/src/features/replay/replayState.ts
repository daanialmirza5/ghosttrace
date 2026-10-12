import type { ReplayResponse, ReplayStatus } from "../../types/api";

const CHECKPOINT_EVERY = 100;
export const MAX_GAP_MS = 1500;
export const MIN_GAP_MS = 30;

export interface ReplayState {
  statuses: Record<string, ReplayStatus>;
  errorTotals: Record<string, number>;
}

/**
 * Folds frame deltas into full state. Checkpoints every 100 frames make seeking cheap;
 * the result for index i is identical however it is reached (forward, backward, jump).
 */
export class ReplayStateIndex {
  private readonly checkpoints: ReplayState[] = [];

  constructor(private readonly replay: ReplayResponse) {
    let state: ReplayState = { statuses: { ...replay.initial_state }, errorTotals: {} };
    replay.frames.forEach((frame, index) => {
      state = {
        statuses: { ...state.statuses, ...frame.node_updates },
        errorTotals: { ...state.errorTotals, ...frame.error_totals },
      };
      if (index % CHECKPOINT_EVERY === 0) this.checkpoints.push(state);
    });
  }

  stateAt(index: number): ReplayState {
    if (this.replay.frames.length === 0 || index < 0) {
      return { statuses: { ...this.replay.initial_state }, errorTotals: {} };
    }
    const clamped = Math.min(index, this.replay.frames.length - 1);
    const checkpointIndex = Math.floor(clamped / CHECKPOINT_EVERY);
    let state = this.checkpoints[checkpointIndex]!;
    for (let i = checkpointIndex * CHECKPOINT_EVERY + 1; i <= clamped; i += 1) {
      const frame = this.replay.frames[i]!;
      state = { statuses: { ...state.statuses, ...frame.node_updates }, errorTotals: { ...state.errorTotals, ...frame.error_totals } };
    }
    return state;
  }
}

/** Real-time gap to the next frame, scaled by speed; idle gaps are capped. */
export function playbackDelay(replay: ReplayResponse, index: number, speed: number): number {
  const current = replay.frames[index];
  const next = replay.frames[index + 1];
  if (!current || !next) return MIN_GAP_MS;
  const gap = (next.offset_ms - current.offset_ms) / speed;
  return Math.max(MIN_GAP_MS, Math.min(MAX_GAP_MS, gap));
}
