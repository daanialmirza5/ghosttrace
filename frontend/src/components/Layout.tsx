import {
  Activity,
  BookOpen,
  FileText,
  GitCompare,
  LayoutDashboard,
  ListTree,
  Network,
  PlayCircle,
  Settings,
  Siren,
  Upload,
  type LucideIcon,
} from "lucide-react";
import { Suspense } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { useReadiness } from "../hooks/queries";
import { Loading, cx } from "./ui";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
}

const NAV: { section: string; items: NavItem[] }[] = [
  { section: "Overview", items: [{ to: "/", label: "Dashboard", icon: LayoutDashboard, end: true }] },
  { section: "Data", items: [{ to: "/import", label: "Import events", icon: Upload }] },
  {
    section: "Investigate",
    items: [
      { to: "/incidents", label: "Incidents", icon: Siren },
      { to: "/timeline", label: "Timeline", icon: ListTree },
      { to: "/graph", label: "Service graph", icon: Network },
      { to: "/replay", label: "Replay", icon: PlayCircle },
    ],
  },
  {
    section: "Analyze",
    items: [
      { to: "/compare", label: "Compare", icon: GitCompare },
      { to: "/reports", label: "Reports", icon: FileText },
    ],
  },
  {
    section: "System",
    items: [
      { to: "/settings", label: "Settings", icon: Settings },
      { to: "/help", label: "Help", icon: BookOpen },
    ],
  },
];

function ApiStatus() {
  const { data, isError, isLoading } = useReadiness();
  const ready = data?.status === "ready";
  const label = isLoading ? "Checking API…" : isError ? "API unreachable" : ready ? "API ready" : "API not ready";
  return (
    <span className="inline-flex items-center gap-2 text-xs text-slate-600" role="status" aria-live="polite">
      <span className={cx("h-2 w-2 rounded-full", isLoading ? "bg-slate-300" : ready ? "bg-emerald-500" : "bg-red-500")} aria-hidden />
      {label}
    </span>
  );
}

export function Layout() {
  return (
    <div className="flex min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2">
        Skip to content
      </a>
      <aside className="sticky top-0 hidden h-screen w-60 flex-none flex-col border-r border-slate-200 bg-white md:flex">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <img src="/favicon.svg" alt="" className="h-7 w-7" />
          <div>
            <p className="text-sm font-semibold tracking-tight text-slate-900">GhostTrace</p>
            <p className="text-[11px] text-slate-500">Incident reconstruction</p>
          </div>
        </div>
        <nav aria-label="Main" className="flex-1 space-y-5 overflow-y-auto px-3 pb-6">
          {NAV.map((group) => (
            <div key={group.section}>
              <p className="px-2 pb-1.5 text-[11px] font-medium tracking-wider text-slate-400 uppercase">{group.section}</p>
              <ul className="space-y-0.5">
                {group.items.map(({ to, label, icon: Icon, end }) => (
                  <li key={to}>
                    <NavLink
                      to={to}
                      end={end}
                      className={({ isActive }) =>
                        cx(
                          "flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm",
                          isActive ? "bg-accent-50 font-medium text-accent-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
                        )
                      }
                    >
                      <Icon className="h-4 w-4" aria-hidden />
                      {label}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
        <div className="border-t border-slate-100 px-5 py-3">
          <ApiStatus />
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3 md:hidden">
          <span className="flex items-center gap-2 font-semibold">
            <Activity className="h-4 w-4 text-accent-600" aria-hidden /> GhostTrace
          </span>
          <ApiStatus />
        </header>
        <nav aria-label="Mobile" className="flex gap-1 overflow-x-auto border-b border-slate-200 bg-white px-2 py-2 md:hidden">
          {NAV.flatMap((group) => group.items).map(({ to, label, end }) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => cx("rounded-md px-2 py-1 text-xs whitespace-nowrap", isActive ? "bg-accent-50 text-accent-700" : "text-slate-600")}>
              {label}
            </NavLink>
          ))}
        </nav>
        <main id="main" className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 md:px-8">
          <Suspense fallback={<Loading />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
    </div>
  );
}
