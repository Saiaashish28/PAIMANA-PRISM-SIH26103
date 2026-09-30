import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ClipboardCheck, FileSearch, Info, Plus, Printer } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ChatPanel } from "../components/ChatPanel";
import { EChart } from "../components/EChart";
import { Card, ErrorBox, Kpi, Loading, RagBadge, SeverityBadge, Tabs, TrajBadge } from "../components/ui";
import { api, useApi } from "../lib/api";
import { DIM_COLOR, DIM_LABEL, fmtCr, fmtMonth, fmtNum, fmtPct, fmtProb, ministryLabel } from "../lib/format";
import type { Driver, EvidenceItem, Intervention, Meta, Pathway, ProjectDetail } from "../lib/types";

type Series = { method: string; mean: number[]; lower: number[]; upper: number[] };
interface Forecast {
  months: string[]; progress: Series; expenditure: Series; projected_completion: string | null; revised_completion: string;
  additional_slip_months: number | null; velocity_pp_per_month: number; revised_cost_cr: number; original_cost_cr: number;
}
type Row = Record<string, number | string | null>;
interface Scen { key: string; label: string; risk_composite: number; risk_cost: number; risk_schedule: number; risk_implementation: number; delta_composite?: number }
interface Analogue {
  project_id: string; project_name: string; sector: string; matched_month: string; similarity: number; progress_then: number;
  cost_growth_then: number; slip_then: number; final_cost_growth_pct: number; final_slip_months: number;
}
interface Trust { score: Record<string, number | string>; issues: { month: string; label: string; issue: string }[] }

const grid = { left: 48, right: 18, top: 30, bottom: 30 };
const split = { splitLine: { lineStyle: { color: "#f1f5f9" } } };

/** 80% prediction band (stacked lower + width) plus the dashed mean forecast line. */
function band(s: Series, color: string, name: string) {
  return [
    { type: "line", name: `${name} lower`, data: s.lower, stack: `${name}-band`, symbol: "none", lineStyle: { opacity: 0 }, tooltip: { show: false } },
    { type: "line", name: `${name} 80% band`, data: s.upper.map((u, i) => +(u - s.lower[i]).toFixed(2)), stack: `${name}-band`, symbol: "none",
      lineStyle: { opacity: 0 }, areaStyle: { color, opacity: 0.15 }, tooltip: { show: false } },
    { type: "line", name: `${name} forecast`, data: s.mean, symbol: "none", color, lineStyle: { type: "dashed", color, width: 2 } },
  ];
}

export default function ProjectPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const p = useApi<ProjectDetail>(`/projects/${id}`);
  const ts = useApi<Row[]>(`/projects/${id}/timeseries`);
  const fc = useApi<Forecast>(`/projects/${id}/forecast`);
  const [hz, setHz] = useState(6);
  const ex = useApi<Record<string, Driver[]>>(`/projects/${id}/explain?horizon=${hz}`);
  const sc = useApi<{ disclaimer: string; scenarios: Scen[] }>(`/projects/${id}/scenarios`);
  const an = useApi<Analogue[]>(`/projects/${id}/analogues`);
  const tr = useApi<Trust>(`/projects/${id}/trust`);
  const ev = useApi<{ items: EvidenceItem[]; pathways: Pathway[] }>(`/projects/${id}/evidence`);
  const iv = useApi<{ items: Intervention[] }>(`/interventions?project_id=${id}`);
  const meta = useApi<Meta>("/meta");
  const [tab, setTab] = useState<"overview" | "drivers" | "forecast" | "evidence" | "actions">("overview");

  const charts = useMemo(() => {
    if (!ts.data || !fc.data) return null;
    const hist = ts.data;
    const hm = hist.map((r) => r.report_month as string);
    const all = [...hm, ...fc.data.months];
    const pad = (arr: (number | null)[], before: number) => [...Array(before).fill(null), ...arr];
    const risk = {
      tooltip: { trigger: "axis" }, legend: { top: 0 }, grid,
      xAxis: { type: "category", data: hm.map(fmtMonth), boundaryGap: false },
      yAxis: { type: "value", min: 0, max: 100, ...split },
      series: [
        { name: "Composite", type: "line", data: hist.map((r) => r.risk_composite), symbol: "none", color: "#0f172a", lineStyle: { width: 3, color: "#0f172a" },
          markArea: { itemStyle: { color: "rgba(220,38,38,0.05)" }, data: [[{ yAxis: 45 }, { yAxis: 100 }]] } },
        ...(["cost", "schedule", "implementation"] as const).map((d) => ({
          name: DIM_LABEL[d], type: "line", data: hist.map((r) => r[`risk_${d}`]), symbol: "none", color: DIM_COLOR[d], lineStyle: { width: 1.5, color: DIM_COLOR[d] },
        })),
      ],
    };
    const progress = {
      tooltip: { trigger: "axis" }, legend: { top: 0, data: ["Reported", "Validated", "Planned (original)", "Progress forecast"] }, grid,
      xAxis: { type: "category", data: all.map(fmtMonth), boundaryGap: false },
      yAxis: { type: "value", min: 0, max: 100, ...split },
      series: [
        { name: "Reported", type: "scatter", symbolSize: 4, data: hist.map((r) => r.physical_progress_pct), color: "#94a3b8" },
        { name: "Validated", type: "line", data: hist.map((r) => r.progress), symbol: "none", color: "#1e40af", lineStyle: { width: 2.5, color: "#1e40af" } },
        { name: "Planned (original)", type: "line", data: hist.map((r) => r.expected_progress), symbol: "none", color: "#64748b", lineStyle: { type: "dotted", color: "#64748b" } },
        ...band(fc.data.progress, "#1e40af", "Progress").map((s) => ({ ...s, data: pad(s.data as number[], hm.length) })),
      ],
    };
    const money = {
      tooltip: { trigger: "axis" }, legend: { top: 0, data: ["Cumulative expenditure", "Revised cost", "Expenditure forecast"] }, grid: { ...grid, left: 60 },
      xAxis: { type: "category", data: all.map(fmtMonth), boundaryGap: false },
      yAxis: { type: "value", name: "₹ Cr", ...split },
      series: [
        { name: "Cumulative expenditure", type: "line", data: hist.map((r) => r.expenditure), symbol: "none", color: "#0d9488", lineStyle: { width: 2.5, color: "#0d9488" }, areaStyle: { color: "rgba(13,148,136,0.08)" } },
        { name: "Revised cost", type: "line", step: "end", data: hist.map((r) => r.revised_cost_cr), symbol: "none", color: "#7c3aed", lineStyle: { width: 2, color: "#7c3aed" } },
        ...band(fc.data.expenditure, "#0d9488", "Expenditure").map((s) => ({ ...s, data: pad(s.data as number[], hm.length) })),
      ],
    };
    return { risk, progress, money };
  }, [ts.data, fc.data]);

  if (p.isLoading) return <Loading />;
  if (p.error || !p.data) return <ErrorBox error={p.error} />;
  const d = p.data;
  const remarks = (ts.data ?? []).filter((r) => r.remarks).slice(-8).reverse();

  return (
    <>
      <div className="mb-3 flex items-center justify-between print:hidden">
        <Link to="/projects" className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800"><ArrowLeft className="h-4 w-4" /> Projects</Link>
        <button className="btn-ghost text-xs" onClick={() => window.print()}><Printer className="h-3.5 w-3.5" /> Print project brief</button>
      </div>
      <div className="card mb-4 flex flex-wrap items-start justify-between gap-4 p-5">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold text-slate-900">{d.project_name}</h1>
            <RagBadge rag={d.rag} /> <TrajBadge t={d.trajectory} />
          </div>
          <p className="mt-1 text-sm text-slate-500">{d.project_id} · {ministryLabel(d.ministry)} · {d.sector} · {d.state}</p>
          <p className="muted mt-1">Agency: {d.implementing_agency} · Contractor: {d.contractor_name} · Started {fmtMonth(d.start_date)} · Last report {fmtMonth(d.report_month)}</p>
        </div>
        <div className="flex gap-6 text-right">
          <div><div className="muted">Composite risk</div><div className="text-2xl font-semibold tabular-nums">{fmtNum(d.risk_composite)}</div>
            <div className="muted">{d.risk_velocity >= 0 ? "+" : ""}{fmtNum(d.risk_velocity, 2)} pts/month</div></div>
          <div><div className="muted">Priority index</div><div className="text-2xl font-semibold tabular-nums text-brand-700">{fmtNum(d.priority_index)}</div></div>
          <div><div className="muted">Data confidence</div><div className="text-2xl font-semibold tabular-nums">{fmtNum(d.data_confidence, 0)}</div><div className="muted">{d.confidence_grade}</div></div>
        </div>
      </div>

      <Tabs value={tab} onChange={setTab} tabs={[
        { key: "overview", label: "Overview & warnings", badge: d.warnings.length ? <span className="chip bg-red-100 text-red-700">{d.warnings.length}</span> : null },
        { key: "drivers", label: "Risk drivers & overrun" },
        { key: "forecast", label: "Forecast" },
        { key: "evidence", label: "Analogues & remarks" },
        { key: "actions", label: "Decisions & assistant" },
      ]} />
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="Physical progress" value={fmtPct(d.progress)} hint={`planned ${fmtPct(d.expected_progress)} · gap ${fmtNum(d.completion_gap)} pp`} />
        <Kpi label="Cost" value={fmtCr(d.revised_cost_cr)} tone={d.cost_growth_pct > 20 ? "red" : d.cost_growth_pct > 0 ? "amber" : "default"}
          hint={`sanctioned ${fmtCr(d.original_cost_cr)} · ${d.cost_growth_pct >= 0 ? "+" : ""}${fmtPct(d.cost_growth_pct)} (${d.n_cost_revisions} revisions)`} />
        <Kpi label="Schedule" value={fmtMonth(d.revised_completion)} tone={d.slip_months > 12 ? "red" : d.slip_months > 0 ? "amber" : "default"}
          hint={`original ${fmtMonth(d.original_completion)} · ${d.slip_months} months slip`} />
        <Kpi label="Progress velocity" value={`${fmtNum(d.velocity_3m, 2)} pp/mo`} tone={d.velocity_3m < d.required_velocity ? "amber" : "green"}
          hint={`required ${fmtNum(d.required_velocity, 2)} pp/mo to meet revised date`} />
      </div>

      <div className={tab === "overview" ? "" : "hidden print:block"}>
      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card title="Early-warning probabilities" subtitle="Probability of an adverse event within each horizon; outlined cells exceed the calibrated alert threshold">
          <table className="w-full text-sm">
            <thead><tr className="muted"><th className="py-1 text-left font-medium">Dimension</th>{[3, 6, 12].map((h) => <th key={h} className="font-medium">{h} mo</th>)}</tr></thead>
            <tbody>
              {(["cost", "schedule", "implementation"] as const).map((dim) => (
                <tr key={dim}>
                  <td className="py-1.5 pr-2 text-slate-700">{DIM_LABEL[dim]}</td>
                  {[3, 6, 12].map((h) => {
                    const v = d.probabilities[dim][String(h)];
                    const over = v >= d.thresholds[dim][String(h)];
                    return (
                      <td key={h} className="p-1">
                        <div className={`rounded-md py-2 text-center font-semibold tabular-nums ${over ? "ring-2 ring-slate-800" : ""}`}
                          style={{ background: `rgba(220,38,38,${0.08 + v * 0.75})`, color: v > 0.5 ? "white" : "#0f172a" }}
                          title={`threshold ${fmtProb(d.thresholds[dim][String(h)])}`}>{fmtProb(v)}</div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-3 space-y-1.5">
            {d.warnings.length === 0 && <p className="muted">No active warnings.</p>}
            {d.warnings.map((w, i) => (
              <div key={i} className="flex items-center justify-between rounded-lg bg-slate-50 px-2.5 py-1.5 text-sm">
                <span>{w.warning} within <b>{w.horizon_months} months</b></span><SeverityBadge s={w.severity} />
              </div>
            ))}
          </div>
        </Card>
        <Card className="xl:col-span-2" title="Risk trajectory" subtitle="Model-scored risk at every reporting month — shows whether risk is building, not just where it is">
          {charts ? <EChart option={charts.risk} height={300} /> : <Loading />}
        </Card>
      </div>
      </div>
      <div className={tab === "forecast" ? "" : "hidden print:block"}>
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card title="Physical progress & forecast"
          subtitle={fc.data ? `${fc.data.progress.method}; projected completion ${fmtMonth(fc.data.projected_completion)}${fc.data.additional_slip_months !== null ? ` (${fc.data.additional_slip_months >= 0 ? "+" : ""}${fc.data.additional_slip_months} months vs revised date)` : ""}` : ""}>
          {charts ? <EChart option={charts.progress} height={300} /> : <Loading />}
        </Card>
        <Card title="Expenditure vs sanctioned cost" subtitle={fc.data ? `${fc.data.expenditure.method}; shaded = 80% prediction interval` : ""}>
          {charts ? <EChart option={charts.money} height={300} /> : <Loading />}
        </Card>
      </div>
      </div>
      <div className={tab === "drivers" ? "" : "hidden print:block"}>
      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2" title="Why is this project at risk? (SHAP)"
          subtitle="Contribution of each factor to the model's log-odds for this project. Red bars raise risk; green lower it. ◆ = non-CUF variable."
          actions={<select className="input" value={hz} onChange={(e) => setHz(Number(e.target.value))}>{[3, 6, 12].map((h) => <option key={h} value={h}>{h}-month model</option>)}</select>}>
          {ex.data ? (
            <div className="grid gap-4 md:grid-cols-3">
              {(["cost", "schedule", "implementation"] as const).map((dim) => {
                const ds = ex.data![dim];
                const max = Math.max(...ds.map((x) => Math.abs(x.shap)), 0.01);
                return (
                  <div key={dim}>
                    <div className="mb-2 text-xs font-semibold" style={{ color: DIM_COLOR[dim] }}>{DIM_LABEL[dim]}</div>
                    <ul className="space-y-2">
                      {ds.slice(0, 6).map((x) => (
                        <li key={x.feature} className="text-xs">
                          <div className="flex justify-between gap-2"><span className="text-slate-700">{x.non_cuf && "◆ "}{x.label}</span><span className="tabular-nums text-slate-500">{x.value ?? "–"}</span></div>
                          <div className="mt-0.5 flex h-2 items-center">
                            <div className="flex h-2 w-1/2 justify-end">{x.shap < 0 && <div className="h-2 rounded-l bg-green-500" style={{ width: `${(Math.abs(x.shap) / max) * 100}%` }} />}</div>
                            <div className="h-3 w-px bg-slate-300" />
                            <div className="h-2 w-1/2">{x.shap > 0 && <div className="h-2 rounded-r bg-red-500" style={{ width: `${(x.shap / max) * 100}%` }} />}</div>
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })}
            </div>
          ) : <Loading />}
        </Card>
        <Card title="Predicted final overrun" subtitle="Quantile gradient boosting trained on completed projects (P10 · P50 · P90)">
          {d.status === "Ongoing" && d.cost_q50 !== null ? (
            <div className="space-y-5">
              {[
                { label: "Final cost growth", unit: "%", cur: d.cost_growth_pct, q: [d.cost_q10!, d.cost_q50!, d.cost_q90!] },
                { label: "Final time overrun", unit: " months", cur: d.slip_months, q: [d.time_q10!, d.time_q50!, d.time_q90!] },
              ].map((m) => {
                const max = Math.max(m.q[2] * 1.15, m.cur * 1.15, 1);
                return (
                  <div key={m.label}>
                    <div className="flex items-baseline justify-between"><span className="text-sm text-slate-700">{m.label}</span>
                      <span className="text-lg font-semibold tabular-nums">{fmtNum(m.q[1])}{m.unit}</span></div>
                    <div className="relative mt-2 h-3 rounded-full bg-slate-100">
                      <div className="absolute h-3 rounded-full bg-brand-100" style={{ left: `${(m.q[0] / max) * 100}%`, width: `${((m.q[2] - m.q[0]) / max) * 100}%` }} />
                      <div className="absolute -top-1 h-5 w-1 rounded bg-brand-700" style={{ left: `${(m.q[1] / max) * 100}%` }} />
                      <div className="absolute -top-1 h-5 w-0.5 bg-slate-500" style={{ left: `${(m.cur / max) * 100}%` }} title="current" />
                    </div>
                    <div className="muted mt-1 flex justify-between"><span>P10 {fmtNum(m.q[0])}{m.unit}</span><span>now {fmtNum(m.cur)}{m.unit}</span><span>P90 {fmtNum(m.q[2])}{m.unit}</span></div>
                  </div>
                );
              })}
            </div>
          ) : <p className="muted">Project completed — final outcome known.</p>}
        </Card>
      </div>
      </div>
      <div className={tab === "overview" ? "" : "hidden print:block"}>
      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card title={<span className="flex items-center gap-1.5"><ClipboardCheck className="h-4 w-4" /> Review pathways</span>}
          subtitle="Evidence-linked options for the administrator — PRISM supports, it does not decide">
          {ev.data ? (
            <ol className="space-y-3 text-sm">
              {ev.data.pathways.length === 0 && <p className="muted">No elevated drivers — continue routine monitoring.</p>}
              {ev.data.pathways.map((pw, i) => (
                <li key={i} className="flex gap-2">
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand-700 text-[11px] font-semibold text-white">{i + 1}</span>
                  <div><div className="text-slate-800">{pw.text}</div><div className="muted">because {pw.because}</div></div>
                </li>
              ))}
            </ol>
          ) : <Loading />}
        </Card>
        <Card className="xl:col-span-2" title="What-if scenarios" subtitle={sc.data?.disclaimer}>
          {sc.data ? (
            <EChart height={230} option={{
              tooltip: { trigger: "axis" }, legend: { top: 0 }, grid: { left: 250, right: 30, top: 30, bottom: 20 },
              xAxis: { type: "value", max: 100, ...split }, yAxis: { type: "category", inverse: true, data: sc.data.scenarios.map((s) => s.label), axisLabel: { width: 240, overflow: "truncate" } },
              series: [
                { name: "Composite", type: "bar", data: sc.data.scenarios.map((s) => s.risk_composite), itemStyle: { color: "#0f172a", borderRadius: 3 }, barGap: "10%" },
                ...(["cost", "schedule", "implementation"] as const).map((dim) => ({ name: DIM_LABEL[dim], type: "bar", data: sc.data!.scenarios.map((s) => s[`risk_${dim}`]), itemStyle: { color: DIM_COLOR[dim], borderRadius: 3 } })),
              ],
            }} />
          ) : <Loading />}
        </Card>
      </div>
      </div>
      <div className={tab === "evidence" ? "" : "hidden print:block"}>
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card title={<span className="flex items-center gap-1.5"><FileSearch className="h-4 w-4" /> Historical analogues</span>}
          subtitle="Completed projects that looked like this one at the same stage — and how they finished" bodyClass="p-0">
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead><tr><th>Project</th><th className="text-right">Similarity</th><th className="text-right">Then: progress / cost / slip</th><th className="text-right">Final cost growth</th><th className="text-right">Final slip</th></tr></thead>
              <tbody>
                {an.data?.map((a) => (
                  <tr key={a.project_id}>
                    <td className="min-w-52"><Link to={`/projects/${a.project_id}`} className="font-medium text-brand-700 hover:underline">{a.project_name}</Link><div className="muted">matched at {fmtMonth(a.matched_month)}</div></td>
                    <td className="text-right tabular-nums">{fmtNum(a.similarity * 100, 0)}%</td>
                    <td className="text-right tabular-nums">{fmtPct(a.progress_then, 0)} / {fmtPct(a.cost_growth_then, 0)} / {a.slip_then} mo</td>
                    <td className="text-right font-semibold tabular-nums">{fmtPct(a.final_cost_growth_pct)}</td>
                    <td className="text-right font-semibold tabular-nums">{a.final_slip_months} mo</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <Card title="Reported remarks (bottleneck extraction)" subtitle={`Current bottleneck: ${d.bottleneck_label}${d.bottleneck_streak > 0 ? ` — unresolved for ${d.bottleneck_streak} months` : ""}`}>
          {remarks.length === 0 && <p className="muted">This data source carries no free-text remarks for the project, so bottleneck extraction has nothing to read.</p>}
          <ul className="max-h-72 space-y-2 overflow-y-auto text-sm">
            {remarks.map((r, i) => (
              <li key={i} className="flex gap-3">
                <span className="muted w-16 shrink-0">{fmtMonth(r.report_month as string)}</span>
                <div><div className="text-slate-700">{r.remarks}</div>
                  <span className="chip mt-0.5 bg-slate-100 text-slate-600">{meta.data?.bottleneck_labels[r.bottleneck as string] ?? r.bottleneck}</span></div>
              </li>
            ))}
          </ul>
        </Card>
      </div>
      </div>
      <div className={tab === "actions" ? "" : "hidden print:block"}>
      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card title="Data trust" subtitle="Checked before any prediction is made">
          {tr.data ? (
            <div className="space-y-2 text-sm">
              {["completeness_score", "freshness_score", "consistency_score", "stability_score"].map((k) => (
                <div key={k}>
                  <div className="flex justify-between"><span className="capitalize text-slate-600">{k.replace("_score", "")}</span><span className="tabular-nums">{fmtNum(tr.data!.score[k] as number, 0)}</span></div>
                  <div className="h-1.5 rounded-full bg-slate-100"><div className="h-1.5 rounded-full bg-brand-600" style={{ width: `${tr.data!.score[k]}%` }} /></div>
                </div>
              ))}
              <div className="muted pt-1">{tr.data.score.staleness_months as number} month(s) stale · {tr.data.score.n_contradictions as number} contradictions · {tr.data.score.n_anomalies as number} anomalies</div>
              <ul className="max-h-40 space-y-1 overflow-y-auto border-t border-slate-100 pt-2 text-xs">
                {tr.data.issues.slice(0, 20).map((x, i) => <li key={i}><span className="muted mr-2">{fmtMonth(x.month)}</span>{x.label}</li>)}
                {tr.data.issues.length === 0 && <li className="muted">No data issues detected.</li>}
              </ul>
            </div>
          ) : <Loading />}
        </Card>
        <InterventionsCard projectId={id} items={iv.data?.items} actionTypes={meta.data?.action_types ?? {}}
          onCreated={() => { qc.invalidateQueries({ queryKey: [`/interventions?project_id=${id}`] }); qc.invalidateQueries({ queryKey: [`/projects/${id}/evidence`] }); }} />
        <Card title="Ask PRISM about this project" subtitle="Local LLM with evidence grounding">
          <ChatPanel projectId={id} height={380} suggestions={["Why is this project at risk?", "What should we do next?", "When will it complete?", "Is the data reliable?", "How did similar projects end?"]} />
        </Card>
      </div>
      </div>
    </>
  );
}

function InterventionsCard({ projectId, items, actionTypes, onCreated }: {
  projectId: string; items?: Intervention[]; actionTypes: Record<string, string>; onCreated: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ action_type: "pmg_review", description: "", authority: "IPMD" });
  const [err, setErr] = useState<string | null>(null);
  const submit = async () => {
    setErr(null);
    try {
      await api("/interventions", { method: "POST", body: JSON.stringify({ project_id: projectId, ...form }) });
      setOpen(false);
      setForm({ ...form, description: "" });
      onCreated();
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const tone = (o: string) => o === "Improved" ? "bg-green-100 text-green-700" : o === "Worsened" ? "bg-red-100 text-red-700" : o.startsWith("Pending") ? "bg-blue-100 text-blue-700" : "bg-slate-100 text-slate-600";
  return (
    <Card title="Decision record & outcome monitor" subtitle="Log an administrative action; PRISM tracks risk after it (closed loop)"
      actions={<button className="btn-ghost text-xs" onClick={() => setOpen(!open)}><Plus className="h-3.5 w-3.5" /> Log action</button>}>
      {open && (
        <div className="mb-3 space-y-2 rounded-lg bg-slate-50 p-3">
          <select className="input w-full" value={form.action_type} onChange={(e) => setForm({ ...form, action_type: e.target.value })}>
            {Object.entries(actionTypes).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <textarea className="input w-full" rows={2} placeholder="Decision and reasoning (e.g. taken up in PMG review; state to hand over balance RoW)"
            value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          <input className="input w-full" placeholder="Authority" value={form.authority} onChange={(e) => setForm({ ...form, authority: e.target.value })} />
          {err && <div className="text-xs text-red-600">{err}</div>}
          <button className="btn w-full justify-center" disabled={form.description.length < 3} onClick={submit}>Record decision</button>
        </div>
      )}
      <ul className="max-h-80 space-y-2 overflow-y-auto text-sm">
        {items?.length === 0 && <li className="muted flex items-center gap-1"><Info className="h-3.5 w-3.5" /> No actions recorded for this project.</li>}
        {items?.map((x) => (
          <li key={x.id} className="rounded-lg border border-slate-100 p-2.5">
            <div className="flex items-start justify-between gap-2">
              <div><div className="font-medium text-slate-800">{actionTypes[x.action_type] ?? x.action_type}</div><div className="muted">{fmtMonth(x.intervention_month)} · {x.authority} · {x.source}</div></div>
              <span className={`chip ${tone(x.outcome)}`}>{x.outcome}</span>
            </div>
            <div className="mt-1 text-xs text-slate-600">{x.description}</div>
            {x.delta_risk !== null && x.delta_risk !== undefined && (
              <div className="muted mt-1">Risk {fmtNum(x.risk_before)} → {fmtNum(x.risk_after_6m ?? x.risk_after_3m ?? null)} ({x.delta_risk > 0 ? "+" : ""}{fmtNum(x.delta_risk)}; {x.excess_vs_control !== null && x.excess_vs_control !== undefined ? `${x.excess_vs_control > 0 ? "+" : ""}${fmtNum(x.excess_vs_control)} vs control` : ""})</div>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}
