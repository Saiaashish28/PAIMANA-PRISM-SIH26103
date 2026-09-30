import clsx from "clsx";
import {
  Activity, BarChart3, Bot, Database, FolderKanban, FolderUp, Gauge, Handshake, IndianRupee, LineChart,
  Bell as BellIcon, Map as MapIcon, Menu, Network, Radio, Scale, Search, Siren, X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { qs, useApi } from "../lib/api";
import { fmtMonth } from "../lib/format";
import type { Health, ProjectSummary } from "../lib/types";
import { KIND_LABEL, SEV_STYLE, timeAgo, useLive } from "../lib/live";
import { Wordmark } from "./Logo";
import { RagBadge } from "./ui";

const NAV = [
  { group: "Monitor", items: [
    { to: "/", label: "Overview", icon: Gauge, end: true },
    { to: "/live", label: "Live feed", icon: Radio },
    { to: "/trends", label: "Portfolio trends", icon: LineChart },
    { to: "/warnings", label: "Early warnings", icon: Siren },
    { to: "/projects", label: "Projects", icon: FolderKanban },
    { to: "/map", label: "Geographic view", icon: MapIcon },
  ] },
  { group: "Analyse", items: [
    { to: "/benchmarking", label: "Benchmarking", icon: Scale },
    { to: "/cost-drivers", label: "Cost drivers", icon: IndianRupee },
    { to: "/intelligence", label: "Systemic patterns", icon: Network },
    { to: "/models", label: "Model benchmark", icon: BarChart3 },
  ] },
  { group: "Act", items: [
    { to: "/interventions", label: "Interventions", icon: Handshake },
    { to: "/assistant", label: "PRISM assistant", icon: Bot },
  ] },
  { group: "Data", items: [
    { to: "/trust", label: "Data trust", icon: Database },
    { to: "/data", label: "Data sources", icon: FolderUp },
  ] },
];

function GlobalSearch() {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const navigate = useNavigate();
  const box = useRef<HTMLDivElement>(null);
  const { data } = useApi<{ items: ProjectSummary[] }>(q.trim().length >= 2 ? `/projects${qs({ q: q.trim(), status: "all", limit: 8 })}` : null);
  const items = data?.items ?? [];

  useEffect(() => {
    const close = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    const key = (e: KeyboardEvent) => {
      if (e.key === "/" && !(e.target as HTMLElement).closest("input,textarea,select")) {
        e.preventDefault();
        box.current?.querySelector("input")?.focus();
      }
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", key); };
  }, []);

  const go = (id: string) => { setOpen(false); setQ(""); navigate(`/projects/${id}`); };
  return (
    <div ref={box} className="relative w-full max-w-md">
      <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
      <input className="input w-full pl-8 pr-10" placeholder="Search projects by name or ID…" value={q}
        onFocus={() => setOpen(true)}
        onChange={(e) => { setQ(e.target.value); setOpen(true); setActive(0); }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") setActive((a) => Math.min(a + 1, items.length - 1));
          if (e.key === "ArrowUp") setActive((a) => Math.max(a - 1, 0));
          if (e.key === "Enter" && items[active]) go(items[active].project_id);
          if (e.key === "Escape") setOpen(false);
        }} />
      <kbd className="absolute right-2 top-2 rounded border border-slate-200 px-1.5 text-[10px] text-slate-400">/</kbd>
      {open && q.trim().length >= 2 && (
        <div className="absolute z-[1000] mt-1 w-full overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg">
          {items.length === 0 && <div className="p-3 text-sm text-slate-500">No matching projects</div>}
          {items.map((p, i) => (
            <button key={p.project_id} onMouseEnter={() => setActive(i)} onClick={() => go(p.project_id)}
              className={clsx("flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm", i === active && "bg-slate-50")}>
              <span className="min-w-0">
                <span className="block truncate font-medium text-slate-800">{p.project_name}</span>
                <span className="block truncate text-xs text-slate-500">{p.project_id} · {p.ministry}</span>
              </span>
              <RagBadge rag={p.rag} />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function LiveIndicator() {
  const { status, lastUpdate } = useLive();
  const live = status === "live";
  return (
    <NavLink to="/live" title={lastUpdate ? `Data refreshed ${lastUpdate.toLocaleTimeString()}` : "Live feed"}
      className={clsx("chip gap-1.5 border text-xs", live ? "border-green-200 bg-green-50 text-green-700" : "border-slate-200 bg-slate-50 text-slate-500")}>
      <span className={clsx("h-2 w-2 rounded-full", live ? "live-dot bg-green-500" : "bg-slate-400")} />
      {live ? "Live" : status === "connecting" ? "Connecting…" : "Reconnecting…"}
    </NavLink>
  );
}

function Bell() {
  const { events, unread, markRead } = useLive();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  return (
    <div ref={box} className="relative">
      <button className="relative rounded-lg p-1.5 text-slate-600 hover:bg-slate-100" aria-label="Notifications"
        onClick={() => { setOpen(!open); markRead(); }}>
        <BellIcon className="h-5 w-5" />
        {unread > 0 && <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold text-white">{unread > 99 ? "99+" : unread}</span>}
      </button>
      {open && (
        <div className="absolute right-0 z-[1000] mt-2 w-96 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
            <span className="text-sm font-semibold">Live feed</span>
            <NavLink to="/live" onClick={() => setOpen(false)} className="text-xs font-medium text-brand-600 hover:underline">Open feed →</NavLink>
          </div>
          <ul className="max-h-96 divide-y divide-slate-100 overflow-y-auto">
            {events.length === 0 && <li className="p-4 text-sm text-slate-500">No events yet.</li>}
            {events.slice(0, 12).map((e, i) => (
              <li key={e.id ?? `t${i}`} className="px-4 py-2.5 text-sm">
                <div className="flex items-center gap-2 text-[11px]">
                  <span className={clsx("chip border", SEV_STYLE[e.severity])}>{KIND_LABEL[e.kind]}</span>
                  <span className="text-slate-400">{timeAgo(e.ts)}</span>
                </div>
                {e.project_id
                  ? <NavLink to={`/projects/${e.project_id}`} onClick={() => setOpen(false)} className="mt-1 line-clamp-2 block font-medium text-slate-800 hover:text-brand-700">{e.title}</NavLink>
                  : <div className="mt-1 line-clamp-2 font-medium text-slate-800">{e.title}</div>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Toasts() {
  const { toasts, dismiss } = useLive();
  return (
    <div className="pointer-events-none fixed right-4 top-16 z-[1200] flex w-96 flex-col gap-2 print:hidden">
      {toasts.map((t, i) => (
        <div key={t.id ?? `t${i}`} className={clsx("slide-in pointer-events-auto rounded-xl border bg-white p-3 shadow-lg",
          t.severity === "critical" ? "border-red-300" : t.severity === "high" ? "border-orange-300" : "border-blue-200")}>
          <div className="flex items-start justify-between gap-2">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{KIND_LABEL[t.kind]}</div>
              <div className="text-sm font-medium text-slate-900">{t.title}</div>
              {t.detail && <div className="mt-0.5 line-clamp-2 text-xs text-slate-500">{t.detail}</div>}
            </div>
            <button className="text-slate-400 hover:text-slate-700" onClick={() => dismiss(t)}><X className="h-4 w-4" /></button>
          </div>
        </div>
      ))}
    </div>
  );
}

export function Layout() {
  const { data: health } = useApi<Health>("/health", { refetchInterval: 15_000 });
  const [menu, setMenu] = useState(false);
  const loc = useLocation();
  useEffect(() => { setMenu(false); }, [loc.pathname]);
  const real = health?.data_source === "real";

  return (
    <div className="flex h-full">
      <aside className={clsx("fixed inset-y-0 left-0 z-[1100] w-64 shrink-0 flex-col bg-brand-900 text-slate-200 transition-transform md:static md:flex md:translate-x-0 print:hidden",
        menu ? "flex translate-x-0" : "-translate-x-full md:flex")}>
        <div className="flex items-center gap-2.5 px-5 py-5">
          <Wordmark />
          <button className="ml-auto md:hidden" onClick={() => setMenu(false)}><X className="h-5 w-5" /></button>
        </div>
        <nav className="flex-1 space-y-4 overflow-y-auto px-3 pb-4">
          {NAV.map((g) => (
            <div key={g.group}>
              <div className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-widest text-slate-500">{g.group}</div>
              {g.items.map(({ to, label, icon: Icon, end }) => (
                <NavLink key={to} to={to} end={end}
                  className={({ isActive }) => clsx("flex items-center gap-2.5 rounded-lg px-3 py-1.5 text-sm",
                    isActive ? "bg-white/10 font-medium text-white" : "text-slate-300 hover:bg-white/5 hover:text-white")}>
                  <Icon className="h-4 w-4" /> {label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="space-y-1.5 border-t border-white/10 px-5 py-4 text-[11px] text-slate-400">
          <Link to="/assistant#llm" className="flex items-center gap-1.5 hover:text-white" title="Set up the local LLM (Ollama)">
            <span className={clsx("h-2 w-2 rounded-full", health?.llm?.available ? "bg-green-400" : "bg-slate-500")} />
            {health?.llm?.available ? `LLM ready: ${health.llm.model}` : "LLM off · click to set up Ollama"}
          </Link>
          <div>MoSPI · IPMD · SIH 26103</div>
        </div>
      </aside>
      {menu && <div className="fixed inset-0 z-[1050] bg-black/40 md:hidden" onClick={() => setMenu(false)} />}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="relative z-30 flex items-center gap-3 border-b border-slate-200 bg-white/90 px-4 py-2.5 backdrop-blur md:px-6 print:hidden">
          <button className="md:hidden" onClick={() => setMenu(true)} aria-label="Menu"><Menu className="h-5 w-5" /></button>
          <GlobalSearch />
          <div className="ml-auto hidden items-center gap-3 text-xs sm:flex">
            {health?.building && <span className="chip bg-blue-50 text-blue-700">Retraining…</span>}
            <NavLink to="/data" className={clsx("chip gap-1.5 border", real ? "border-green-200 bg-green-50 text-green-700" : "border-amber-200 bg-amber-50 text-amber-700")}>
              <span className={clsx("h-1.5 w-1.5 rounded-full", real ? "bg-green-500" : "bg-amber-500")} />
              {real ? "Real PAIMANA data" : "Synthetic demo data"}
            </NavLink>
            <span className="flex items-center gap-1 text-slate-500"><Activity className="h-3.5 w-3.5" /> As of {fmtMonth(health?.as_of)}</span>
          </div>
          <LiveIndicator />
          <Bell />
        </header>
        <Toasts />
        <main className="min-w-0 flex-1 overflow-y-auto p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
