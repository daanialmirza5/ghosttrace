# 90-second demo script

**Setup (before the demo):** start the app (`docker run -p 8000:8000 ghosttrace:local`, or the native commands from the README). Open <http://localhost:8000>, or <http://localhost:5173> in development, and **import "Normal traffic (control)"** so the comparison step has a baseline.

| Time | Do | Say |
| --- | --- | --- |
| 0:00 | Dashboard | "GhostTrace reconstructs software incidents from raw application events. Every number on this page comes from the backend; there are no placeholder metrics." |
| 0:10 | **Import events** → *Slow product pages* → **Import** | "This is a synthetic but realistic dataset: about 2,300 events from eight services. It's validated line by line and normalised to one schema." |
| 0:20 | Click **1 incident detected**, then open the incident | "It found one incident from statistical signals: error spikes, latency, failed dependency calls." |
| 0:30 | Overview: hypothesis #1 **redis-cache**, expand the signal table | "Candidates are ranked by six documented signals: who failed first, where failing traces bottom out, who everyone depends on, recent changes, and so on. The score is a heuristic, not a probability, and it's labelled that way." |
| 0:40 | Click an event-ID chip → drawer | "Every claim links to real events. This one is the cache being OOM-killed, and here are the signals and hypotheses that cite it." |
| 0:48 | **Service graph** tab | "The dependency graph comes only from trace ancestry and recorded calls, never from timing alone. Dashed nodes, like the payment provider, are inferred: they emit no logs." |
| 0:56 | **Replay** tab → **Play** at 30× | "The replay steps through the actual events and re-computes service health as it goes. You can watch the cache fail and the failure spread upward." |
| 1:06 | **Compare** → *Compare executions* | "Against the healthy run, the differences pop out: error rates, latency and failing dependencies, normalised per minute." |
| 1:14 | Back to the incident → **Report** → **Generate report** → Download | "The report exports to Markdown or JSON, and every cited event ID is verified against the import first." |
| 1:22 | Open the *ambiguous* dataset's incident (optional) | "When services fail together with no traces linking them, GhostTrace says 'insufficient evidence' instead of guessing." |
| 1:30 | End | "It's FastAPI and React, deterministic, and benchmarked on held-out synthetic seeds; the README documents the limitations." |
