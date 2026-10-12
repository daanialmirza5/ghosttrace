import { AlertTriangle, Inbox, Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode, Ref } from "react";

import { ApiError } from "../services/api";
import type { EvidenceStatus, IncidentSeverity, NodeStatus, Severity, Uncertainty } from "../types/api";

export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent-600 text-white hover:bg-accent-700 disabled:bg-accent-500/60",
  secondary: "border border-slate-300 bg-white text-slate-800 hover:bg-slate-50 disabled:text-slate-400",
  ghost: "text-slate-600 hover:bg-slate-100 hover:text-slate-900 disabled:text-slate-300",
  danger: "border border-red-200 bg-white text-red-700 hover:bg-red-50",
};

export function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  className,
  children,
  disabled,
  ref,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: "sm" | "md";
  loading?: boolean;
  ref?: Ref<HTMLButtonElement>;
}) {
  return (
    <button
      ref={ref}
      type="button"
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors disabled:cursor-not-allowed",
        size === "sm" ? "px-2.5 py-1.5 text-xs" : "px-3.5 py-2 text-sm",
        VARIANTS[variant],
        className,
      )}
      disabled={disabled || loading}
      {...props}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function Card({ title, actions, children, className, padded = true }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; padded?: boolean }) {
  return (
    <section className={cx("card", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
          {title && <h2 className="text-sm font-semibold text-slate-800">{title}</h2>}
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={padded ? "p-4" : undefined}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, description, actions }: { title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-slate-600">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

const TONES = {
  slate: "bg-slate-100 text-slate-700 ring-slate-200",
  red: "bg-red-50 text-red-700 ring-red-200",
  amber: "bg-amber-50 text-amber-800 ring-amber-200",
  green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  blue: "bg-sky-50 text-sky-700 ring-sky-200",
  accent: "bg-accent-50 text-accent-700 ring-accent-100",
} as const;
export type Tone = keyof typeof TONES;

export function Badge({ tone = "slate", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={cx("inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset whitespace-nowrap", TONES[tone])}>
      {children}
    </span>
  );
}

const SEVERITY_TONE: Record<Severity | IncidentSeverity, Tone> = {
  debug: "slate",
  info: "blue",
  warning: "amber",
  error: "red",
  critical: "red",
  major: "amber",
  minor: "slate",
};

export function SeverityBadge({ severity }: { severity: Severity | IncidentSeverity }) {
  return <Badge tone={SEVERITY_TONE[severity]}>{severity}</Badge>;
}

const EVIDENCE: Record<EvidenceStatus, { tone: Tone; label: string; title: string }> = {
  sufficient: { tone: "green", label: "Evidence sufficient", title: "A hypothesis is supported by structural evidence (traces, dependency calls or changes)." },
  ambiguous: { tone: "amber", label: "Ambiguous", title: "Top hypotheses have nearly equal heuristic scores." },
  insufficient: { tone: "red", label: "Insufficient evidence", title: "GhostTrace cannot rank a root cause from the imported events." },
};

export function EvidenceBadge({ status }: { status: EvidenceStatus }) {
  const entry = EVIDENCE[status];
  return (
    <Badge tone={entry.tone} title={entry.title}>
      {entry.label}
    </Badge>
  );
}

export function UncertaintyBadge({ value }: { value: Uncertainty }) {
  const tone: Tone = value === "low" ? "green" : value === "medium" ? "amber" : "red";
  return <Badge tone={tone}>{value} uncertainty</Badge>;
}

export const STATUS_STYLES: Record<NodeStatus, { dot: string; ring: string; label: string }> = {
  healthy: { dot: "bg-emerald-500", ring: "border-emerald-300", label: "Healthy" },
  degraded: { dot: "bg-amber-500", ring: "border-amber-400", label: "Degraded" },
  failing: { dot: "bg-red-500", ring: "border-red-400", label: "Failing" },
  unknown: { dot: "bg-slate-400", ring: "border-slate-300", label: "Unknown" },
};

export function StatusDot({ status, label = true }: { status: NodeStatus; label?: boolean }) {
  const style = STATUS_STYLES[status];
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-slate-700">
      <span className={cx("h-2 w-2 rounded-full", style.dot)} aria-hidden />
      {label ? style.label : <span className="sr-only">{style.label}</span>}
    </span>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 p-6 text-sm text-slate-500">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
      {label}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : "Something went wrong.";
  const requestId = error instanceof ApiError ? error.requestId : null;
  return (
    <div role="alert" className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
      <AlertTriangle className="mt-0.5 h-4 w-4 flex-none" aria-hidden />
      <div className="flex-1">
        <p className="font-medium">{message}</p>
        {requestId && <p className="mt-1 text-xs text-red-700">Request ID: <code>{requestId}</code></p>}
      </div>
      {onRetry && (
        <Button size="sm" variant="secondary" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}

export function EmptyState({ title, description, action }: { title: string; description?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-10 text-center">
      <Inbox className="h-8 w-8 text-slate-300" aria-hidden />
      <p className="text-sm font-medium text-slate-700">{title}</p>
      {description && <p className="max-w-md text-sm text-slate-500">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="card p-4">
      <p className="label">{label}</p>
      <p className="mt-1 text-2xl font-semibold tracking-tight text-slate-900 tabular-nums">{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

export function Field({ label, htmlFor, children, hint }: { label: string; htmlFor: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="space-y-1">
      <label htmlFor={htmlFor} className="block text-sm font-medium text-slate-700">
        {label}
      </label>
      {children}
      {hint && <p className="text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

export function ScoreBar({ value, label }: { value: number; label?: string }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div className="flex items-center gap-2" title={label}>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100" role="meter" aria-valuemin={0} aria-valuemax={1} aria-valuenow={value} aria-label={label ?? "heuristic score"}>
        <div className="h-full rounded-full bg-accent-500" style={{ width: `${pct}%` }} />
      </div>
      <span className="w-10 text-right font-mono text-xs text-slate-600 tabular-nums">{value.toFixed(2)}</span>
    </div>
  );
}
