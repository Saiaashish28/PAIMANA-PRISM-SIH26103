import clsx from "clsx";
import { AlertTriangle, Loader2 } from "lucide-react";
import type { ReactNode } from "react";
import { RAG_COLOR, TRAJ_COLOR } from "../lib/format";

export function Card({ title, subtitle, actions, children, className, bodyClass }: {
  title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClass?: string;
}) {
  return (
    <section className={clsx("card", className)}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-3 border-b border-slate-100 px-4 py-3">
          <div>
            {title && <h3 className="card-title">{title}</h3>}
            {subtitle && <p className="muted mt-0.5">{subtitle}</p>}
          </div>
          {actions}
        </header>
      )}
      <div className={clsx("p-4", bodyClass)}>{children}</div>
    </section>
  );
}

export function Kpi({ label, value, hint, tone = "default", icon }: {
  label: string; value: ReactNode; hint?: ReactNode; tone?: "default" | "red" | "amber" | "green" | "blue"; icon?: ReactNode;
}) {
  const tones = {
    default: "text-slate-900", red: "text-red-600", amber: "text-amber-600", green: "text-green-600", blue: "text-brand-700",
  };
  return (
    <div className="card flex items-start gap-3 p-4">
      {icon && <div className="rounded-lg bg-brand-50 p-2 text-brand-700">{icon}</div>}
      <div className="min-w-0">
        <div className="muted font-medium uppercase tracking-wide">{label}</div>
        <div className={clsx("mt-1 text-2xl font-semibold tabular-nums", tones[tone])}>{value}</div>
        {hint && <div className="muted mt-0.5">{hint}</div>}
      </div>
    </div>
  );
}

export function RagBadge({ rag, className }: { rag: string; className?: string }) {
  const c = RAG_COLOR[rag] ?? "#64748b";
  return (
    <span className={clsx("chip gap-1 border", className)} style={{ color: c, borderColor: `${c}55`, background: `${c}14` }}>
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: c }} />
      {rag}
    </span>
  );
}

export function TrajBadge({ t }: { t: string }) {
  const c = TRAJ_COLOR[t] ?? "#64748b";
  const arrow = t === "Improving" ? "↘" : t === "Stable" ? "→" : t === "Deteriorating" ? "↗" : "⇈";
  return (
    <span className="chip gap-1" style={{ color: c, background: `${c}14` }}>
      {arrow} {t}
    </span>
  );
}

export function SeverityBadge({ s }: { s: string }) {
  const map: Record<string, string> = {
    Critical: "bg-red-100 text-red-700", High: "bg-orange-100 text-orange-700", Watch: "bg-yellow-100 text-yellow-800",
  };
  return <span className={clsx("chip", map[s] ?? "bg-slate-100 text-slate-600")}>{s}</span>;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 p-10 text-sm text-slate-500">
      <Loader2 className="h-4 w-4 animate-spin" /> {label}
    </div>
  );
}

export function ErrorBox({ error }: { error: Error | null }) {
  if (!error) return null;
  return (
    <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
      <AlertTriangle className="h-4 w-4" /> {error.message}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {actions}
    </div>
  );
}

export function Bar({ value, max = 100, color = "#1e40af" }: { value: number; max?: number; color?: string }) {
  return (
    <div className="h-1.5 w-full rounded-full bg-slate-100">
      <div className="h-1.5 rounded-full" style={{ width: `${Math.min(100, (value / max) * 100)}%`, background: color }} />
    </div>
  );
}

export function Select({ value, onChange, options, placeholder }: {
  value: string; onChange: (v: string) => void; options: string[]; placeholder: string;
}) {
  return (
    <select className="input max-w-52" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{placeholder}</option>
      {options.map((o) => <option key={o} value={o}>{o}</option>)}
    </select>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: {
  tabs: { key: T; label: string; badge?: ReactNode }[]; value: T; onChange: (v: T) => void;
}) {
  return (
    <div className="mb-4 flex gap-1 overflow-x-auto border-b border-slate-200 print:hidden">
      {tabs.map((t) => (
        <button key={t.key} onClick={() => onChange(t.key)}
          className={clsx("-mb-px flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition",
            value === t.key ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-800")}>
          {t.label}{t.badge}
        </button>
      ))}
    </div>
  );
}

export function Segmented<T extends string>({ options, value, onChange }: {
  options: { key: T; label: string }[]; value: T; onChange: (v: T) => void;
}) {
  return (
    <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-0.5">
      {options.map((o) => (
        <button key={o.key} onClick={() => onChange(o.key)}
          className={clsx("rounded-md px-2.5 py-1 text-xs font-medium",
            value === o.key ? "bg-white text-brand-700 shadow-sm" : "text-slate-500 hover:text-slate-800")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function ExportButton({ onClick, label = "Export CSV" }: { onClick: () => void; label?: string }) {
  return (
    <button className="btn-ghost text-xs print:hidden" onClick={onClick}>
      <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 3v12m0 0-4-4m4 4 4-4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" /></svg>
      {label}
    </button>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border border-dashed border-slate-200 p-6 text-center text-sm text-slate-500">{children}</div>;
}
