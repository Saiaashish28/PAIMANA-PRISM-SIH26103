import { useQueryClient } from "@tanstack/react-query";
import { ClipboardList, Loader2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { EChart } from "../components/EChart";
import { Card, Empty, ErrorBox, Kpi, Loading, PageHeader, RagBadge, Select, TrajBadge } from "../components/ui";
import { api, qs, useApi } from "../lib/api";
import { fmtMonth, fmtNum } from "../lib/format";
import type { Intervention, Meta } from "../lib/types";

interface Resp {
  control: { n: number; delta_risk_6m: number; velocity_after_6m: number; velocity_before: number };
  effectiveness: { action_type: string; label: string; n: number; improved_pct: number; worsened_pct: number; mean_delta_risk: number; mean_excess_vs_control: number }[];
  outcomes: Record<string, number>;
  n_evaluated: number;
  items: Intervention[];
  caveat: string;
}

interface QueueItem {
  project_id: string; project_name: string; ministry: string; rag: string; trajectory: string; priority_index: number;
  risk_composite: number; warnings: string[]; pathways: { action_type: string; text: string; because: string }[];
}

function ActionQueue({ actionTypes, asOf }: { actionTypes: Record<string, string>; asOf?: string }) {
  const qc = useQueryClient();
  const { data, isLoading, error } = useApi<QueueItem[]>("/interventions/queue?limit=12");
  const [open, setOpen] = useState<string | null>(null);
  const [form, setForm] = useState({ action_type: "pmg_review", description: "", authority: "IPMD", intervention_month: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const start = (q: QueueItem) => {
    const pw = q.pathways[0];
    setForm({ action_type: pw?.action_type ?? "pmg_review", description: pw ? pw.text : "", authority: "IPMD", intervention_month: asOf ?? "" });
    setOpen(q.project_id);
    setErr(null);
  };
  const submit = async (pid: string) => {
    setBusy(true);
    setErr(null);
    try {
      await api("/interventions", { method: "POST", body: JSON.stringify({ project_id: pid, ...form, intervention_month: form.intervention_month || null }) });
      setOpen(null);
      qc.invalidateQueries();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title={<span className="flex items-center gap-1.5"><ClipboardList className="h-4 w-4" /> Action queue</span>}
      subtitle="Highest-priority projects with no decision recorded in the last 3 months, with the review pathway PRISM suggests from the factors driving their risk. Record what was decided; PRISM then tracks the outcome in later reports."
      bodyClass="p-0">
      {isLoading ? <Loading /> : error ? <div className="p-4"><ErrorBox error={error} /></div> : (
        <ul className="divide-y divide-slate-100">
          {data?.length === 0 && <li className="p-4"><Empty>Every high-priority project has a recent decision.</Empty></li>}
          {data?.map((q) => (
            <li key={q.project_id} className="px-4 py-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <Link to={`/projects/${q.project_id}`} className="line-clamp-1 font-medium text-slate-900 hover:text-brand-700">{q.project_name}</Link>
                  <div className="muted">{q.project_id} · {q.ministry} · priority {fmtNum(q.priority_index)} · risk {fmtNum(q.risk_composite)}</div>
                  <div className="mt-1 flex flex-wrap gap-1.5"><RagBadge rag={q.rag} /><TrajBadge t={q.trajectory} />
                    {q.warnings.map((w) => <span key={w} className="chip bg-red-50 text-red-700">{w}</span>)}</div>
                  {q.pathways[0] && <div className="mt-1.5 text-sm text-slate-700">Suggested: <b>{q.pathways[0].text}</b> <span className="muted">— because {q.pathways[0].because}</span></div>}
                </div>
                <button className="btn shrink-0 text-xs" onClick={() => (open === q.project_id ? setOpen(null) : start(q))}>Record decision</button>
              </div>
              {open === q.project_id && (
                <div className="mt-3 grid gap-2 rounded-lg bg-slate-50 p-3 md:grid-cols-4">
                  <select className="input" value={form.action_type} onChange={(e) => setForm({ ...form, action_type: e.target.value })}>
                    {Object.entries(actionTypes).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                  <input className="input md:col-span-2" value={form.description} placeholder="What was decided" onChange={(e) => setForm({ ...form, description: e.target.value })} />
                  <input className="input" value={form.authority} placeholder="Authority" onChange={(e) => setForm({ ...form, authority: e.target.value })} />
                  <label className="muted flex items-center gap-2 md:col-span-2">Decision month
                    <input className="input" type="month" value={form.intervention_month} onChange={(e) => setForm({ ...form, intervention_month: e.target.value })} />
                    <span>(an earlier month is evaluated right away against later reports)</span></label>
                  <div className="flex items-center justify-end gap-2 md:col-span-2">
                    {err && <span className="text-xs text-red-600">{err}</span>}
                    <button className="btn-ghost text-xs" onClick={() => setOpen(null)}>Cancel</button>
                    <button className="btn text-xs" disabled={busy || form.description.length < 3} onClick={() => submit(q.project_id)}>
                      {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Save decision</button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export default function InterventionsPage() {
  const [source, setSource] = useState("");
  const meta = useApi<Meta>("/meta");
  const { data, isLoading, error } = useApi<Resp>(`/interventions${qs({ source, limit: 400 })}`);
  const health = useApi<{ as_of?: string }>("/health");
  if (isLoading) return <Loading />;
  if (error || !data) return <ErrorBox error={error} />;
  const eff = data.effectiveness;
  const tone = (o: string) => o === "Improved" ? "text-green-700" : o === "Worsened" ? "text-red-700" : o.startsWith("Pending") ? "text-blue-700" : "text-slate-600";

  return (
    <>
      <PageHeader title="Closed-loop intervention intelligence"
        subtitle="Every administrative action is recorded with the risk at the time; PRISM then monitors what happened next and compares it with similar situations where no action was taken." />
      <ActionQueue actionTypes={meta.data?.action_types ?? {}} asOf={health.data?.as_of} />
      <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="Actions evaluated" value={data.n_evaluated} hint={`${data.outcomes["Pending (awaiting post-action data)"] ?? 0} awaiting post-action data`} />
        <Kpi label="Improved" tone="green" value={data.outcomes.Improved ?? 0} hint="risk fell ≥5 pts beyond control, or pace recovered" />
        <Kpi label="Worsened" tone="red" value={data.outcomes.Worsened ?? 0} />
        <Kpi label="Control baseline" value={`${fmtNum(data.control.delta_risk_6m)} pts`} hint={`avg 6-month risk change without action (n=${data.control.n})`} />
      </div>
      {eff.length === 0 && (
        <div className="mt-4"><Empty>Effectiveness charts appear once decisions have been recorded and later reports show what followed.
          Use <b>Record decision</b> above — decisions dated in an earlier month are evaluated immediately.</Empty></div>
      )}
      <div className={eff.length ? "mt-4 grid gap-4 xl:grid-cols-2" : "hidden"}>
        <Card title="Effectiveness by action type" subtitle={data.caveat}>
          <EChart height={280} option={{
            tooltip: { trigger: "axis" }, legend: { top: 0 }, grid: { left: 200, right: 30, top: 30, bottom: 20 },
            xAxis: { type: "value", max: 100, axisLabel: { formatter: "{value}%" }, splitLine: { lineStyle: { color: "#f1f5f9" } } },
            yAxis: { type: "category", inverse: true, data: eff.map((e) => `${e.label} (n=${e.n})`) },
            series: [
              { name: "Improved", type: "bar", stack: "o", data: eff.map((e) => e.improved_pct), itemStyle: { color: "#16a34a" } },
              { name: "No material change", type: "bar", stack: "o", data: eff.map((e) => +(100 - e.improved_pct - e.worsened_pct).toFixed(1)), itemStyle: { color: "#cbd5e1" } },
              { name: "Worsened", type: "bar", stack: "o", data: eff.map((e) => e.worsened_pct), itemStyle: { color: "#dc2626" } },
            ],
          }} />
        </Card>
        <Card title="Risk change beyond control" subtitle="Mean 6-month change in composite risk after the action minus the control baseline (negative = better than no action)">
          <EChart height={280} option={{
            tooltip: {}, grid: { left: 200, right: 40, top: 10, bottom: 20 },
            xAxis: { type: "value", splitLine: { lineStyle: { color: "#f1f5f9" } } },
            yAxis: { type: "category", inverse: true, data: eff.map((e) => e.label) },
            series: [{ type: "bar", barWidth: 14, label: { show: true, position: "right", formatter: (p: { value: number }) => p.value.toFixed(1) },
              data: eff.map((e) => ({ value: e.mean_excess_vs_control, itemStyle: { color: e.mean_excess_vs_control <= 0 ? "#16a34a" : "#dc2626", borderRadius: 3 } })) }],
          }} />
        </Card>
      </div>
      <Card className="mt-4" title="Decision records" bodyClass="p-0"
        actions={<Select value={source} onChange={setSource} options={["historical", "user"]} placeholder="All sources" />}>
        <div className="max-h-[60vh] overflow-auto">
          <table className="tbl">
            <thead><tr><th>Month</th><th>Project</th><th>Action</th><th className="text-right">Risk before</th><th className="text-right">After 6m</th><th className="text-right">vs control</th><th>Bottleneck resolved</th><th>Outcome</th></tr></thead>
            <tbody>
              {data.items.length === 0 && (
                <tr><td colSpan={8} className="p-6 text-center text-slate-500">
                  No decisions recorded yet. Log an action from a project's <b>Decisions &amp; assistant</b> tab; PRISM then tracks its risk over the following months.
                </td></tr>
              )}
              {data.items.map((x) => (
                <tr key={x.id}>
                  <td className="whitespace-nowrap">{fmtMonth(x.intervention_month)}</td>
                  <td><Link to={`/projects/${x.project_id}`} className="font-medium text-brand-700 hover:underline">{x.project_name ?? x.project_id}</Link><div className="muted">{x.ministry}</div></td>
                  <td><div>{meta.data?.action_types[x.action_type] ?? x.action_type}</div><div className="muted max-w-xs">{x.description}</div></td>
                  <td className="text-right tabular-nums">{fmtNum(x.risk_before)}</td>
                  <td className="text-right tabular-nums">{fmtNum(x.risk_after_6m ?? null)}</td>
                  <td className="text-right tabular-nums">{x.excess_vs_control === null || x.excess_vs_control === undefined ? "–" : `${x.excess_vs_control > 0 ? "+" : ""}${fmtNum(x.excess_vs_control)}`}</td>
                  <td>{x.bottleneck_resolved_6m === null || x.bottleneck_resolved_6m === undefined ? "–" : x.bottleneck_resolved_6m ? "Yes" : "No"}</td>
                  <td className={`font-medium ${tone(x.outcome)}`}>{x.outcome}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
