import { AlertOctagon, IndianRupee, Lightbulb, Radio, TrendingUp } from "lucide-react";
import clsx from "clsx";
import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { EChart } from "../components/EChart";
import { Card, ErrorBox, Kpi, Loading, PageHeader, RagBadge, TrajBadge } from "../components/ui";
import { useApi } from "../lib/api";
import { DIM_COLOR, DIM_LABEL, RAG_COLOR, TRAJ_COLOR, fmtCr, fmtMonth, fmtNum, fmtPct } from "../lib/format";
import { KIND_LABEL, SEV_STYLE, timeAgo, useLive } from "../lib/live";
import type { ProjectSummary } from "../lib/types";

function LiveActivity() {
  const { events, status } = useLive();
  return (
    <Card title={<span className="flex items-center gap-1.5"><Radio className={clsx("h-4 w-4", status === "live" ? "live-dot text-green-600" : "text-slate-400")} /> Live activity</span>}
      actions={<Link to="/live" className="text-xs font-medium text-brand-600 hover:underline">Live feed →</Link>} bodyClass="p-0">
      <ul className="divide-y divide-slate-100">
        {events.length === 0 && <li className="p-4 text-sm text-slate-500">Waiting for events…</li>}
        {events.slice(0, 6).map((e, i) => (
          <li key={e.id ?? `o${i}`} className="px-4 py-2.5">
            <div className="flex items-center gap-2 text-[11px]"><span className={clsx("chip border", SEV_STYLE[e.severity])}>{KIND_LABEL[e.kind]}</span><span className="text-slate-400">{timeAgo(e.ts)}</span></div>
            {e.project_id ? <Link to={`/projects/${e.project_id}`} className="mt-0.5 line-clamp-2 block text-sm text-slate-800 hover:text-brand-700">{e.title}</Link>
              : <div className="mt-0.5 line-clamp-2 text-sm text-slate-800">{e.title}</div>}
          </li>
        ))}
      </ul>
    </Card>
  );
}

interface Summary {
  as_of: string;
  kpis: Record<string, number>;
  rag: Record<string, number>;
  trajectory: Record<string, number>;
  warnings_by_horizon: Record<string, number>;
  warnings_by_dimension: Record<string, number>;
  risk_history: { report_month: string; avg_risk: number; projects: number }[];
  top_priority: ProjectSummary[];
  risk_matrix: { project_id: string; project_name: string; risk_composite: number; risk_velocity: number; rag: string; revised_cost_cr: number; trajectory: string }[];
  patterns: string[];
}

export default function OverviewPage() {
  const { data, isLoading, error } = useApi<Summary>("/portfolio/summary");
  const navigate = useNavigate();

  const charts = useMemo(() => {
    if (!data) return null;
    const ragOrder = ["Red", "Amber", "Green"];
    const rag = {
      tooltip: { trigger: "item" },
      legend: { bottom: 0, icon: "circle" },
      series: [{
        type: "pie", radius: ["52%", "75%"], center: ["50%", "44%"], avoidLabelOverlap: true,
        label: { show: true, position: "inside", formatter: "{c}", fontWeight: 600, color: "#fff" },
        data: ragOrder.map((k) => ({ name: k, value: data.rag[k] ?? 0, itemStyle: { color: RAG_COLOR[k] } })),
      }],
    };
    const trajOrder = ["Rapidly Deteriorating", "Deteriorating", "Stable", "Improving"];
    const traj = {
      grid: { left: 140, right: 30, top: 10, bottom: 20 },
      xAxis: { type: "value", splitLine: { lineStyle: { color: "#f1f5f9" } } },
      yAxis: { type: "category", data: [...trajOrder].reverse(), axisTick: { show: false } },
      tooltip: {},
      series: [{
        type: "bar", barWidth: 16, label: { show: true, position: "right" },
        data: [...trajOrder].reverse().map((k) => ({ value: data.trajectory[k] ?? 0, itemStyle: { color: TRAJ_COLOR[k], borderRadius: 4 } })),
      }],
    };
    const warn = {
      tooltip: {},
      grid: { left: 40, right: 10, top: 20, bottom: 30 },
      xAxis: { type: "category", data: ["3 months", "6 months", "12 months"] },
      yAxis: { type: "value", name: "projects", splitLine: { lineStyle: { color: "#f1f5f9" } } },
      series: [{
        type: "bar", barWidth: 38, label: { show: true, position: "top" },
        data: ["3", "6", "12"].map((h, i) => ({ value: data.warnings_by_horizon[h] ?? 0, itemStyle: { color: ["#dc2626", "#f97316", "#eab308"][i], borderRadius: [4, 4, 0, 0] } })),
      }],
    };
    const hist = {
      tooltip: { trigger: "axis" },
      grid: { left: 40, right: 16, top: 16, bottom: 30 },
      xAxis: { type: "category", data: data.risk_history.map((r) => fmtMonth(r.report_month)), boundaryGap: false },
      yAxis: { type: "value", name: "avg risk", splitLine: { lineStyle: { color: "#f1f5f9" } } },
      series: [{ type: "line", smooth: true, symbol: "none", data: data.risk_history.map((r) => r.avg_risk?.toFixed(1)),
        lineStyle: { width: 2.5, color: "#1e40af" }, areaStyle: { color: "rgba(30,64,175,0.08)" } }],
    };
    const maxCost = Math.max(...data.risk_matrix.map((r) => r.revised_cost_cr));
    const matrix = {
      tooltip: {
        formatter: (p: { data: [number, number, number, string, string] }) =>
          `<b>${p.data[3]}</b><br/>${p.data[4]}<br/>Risk ${p.data[0].toFixed(1)} · velocity ${p.data[1].toFixed(2)}/mo<br/>${fmtCr(p.data[2])}`,
      },
      grid: { left: 50, right: 20, top: 20, bottom: 40 },
      xAxis: { name: "Composite risk (0-100)", nameLocation: "middle", nameGap: 26, min: 0, max: 100, splitLine: { lineStyle: { color: "#f1f5f9" } } },
      yAxis: { name: "Risk velocity (pts/month)", splitLine: { lineStyle: { color: "#f1f5f9" } } },
      series: ["Red", "Amber", "Green"].map((rag) => ({
        type: "scatter", name: rag,
        data: data.risk_matrix.filter((r) => r.rag === rag).map((r) => [r.risk_composite, r.risk_velocity, r.revised_cost_cr, r.project_id, r.project_name]),
        symbolSize: (d: number[]) => 6 + 22 * Math.sqrt(d[2] / maxCost),
        itemStyle: { color: RAG_COLOR[rag], opacity: 0.7 },
        markLine: rag === "Red" ? { silent: true, symbol: "none", lineStyle: { color: "#94a3b8", type: "dashed" }, data: [{ yAxis: 0 }] } : undefined,
      })),
      legend: { top: 0, right: 10 },
    };
    const dims = {
      tooltip: {},
      grid: { left: 130, right: 30, top: 10, bottom: 20 },
      xAxis: { type: "value", splitLine: { lineStyle: { color: "#f1f5f9" } } },
      yAxis: { type: "category", data: ["implementation", "schedule", "cost"].map((d) => DIM_LABEL[d]) },
      series: [{ type: "bar", barWidth: 16, label: { show: true, position: "right" },
        data: ["implementation", "schedule", "cost"].map((d) => ({ value: data.warnings_by_dimension[d] ?? 0, itemStyle: { color: DIM_COLOR[d], borderRadius: 4 } })) }],
    };
    return { rag, traj, warn, hist, matrix, dims };
  }, [data]);

  if (isLoading) return <Loading />;
  if (error || !data || !charts) return <ErrorBox error={error} />;
  const k = data.kpis;

  return (
    <>
      <PageHeader title="Portfolio overview"
        subtitle={`Central sector infrastructure projects ≥ ₹150 Cr · reporting month ${fmtMonth(data.as_of)}`} />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="Ongoing projects" value={fmtNum(k.ongoing, 0)} hint={`${fmtNum(k.completed, 0)} completed · ${fmtNum(k.projects, 0)} total`} icon={<TrendingUp className="h-4 w-4" />} />
        <Kpi label="Revised cost" value={fmtCr(k.revised_cost_cr)} hint={`ongoing projects · vs ${fmtCr(k.original_cost_cr)} sanctioned (+${fmtPct(k.cost_escalation_pct)})`} icon={<IndianRupee className="h-4 w-4" />} />
        <Kpi label="Red projects" tone="red" value={fmtNum(data.rag.Red ?? 0, 0)} hint={`${fmtNum(data.warnings_by_horizon["3"], 0)} with a 3-month warning of some kind`} icon={<AlertOctagon className="h-4 w-4" />} />
        <Kpi label="Deteriorating" tone="amber" value={fmtNum((data.trajectory["Rapidly Deteriorating"] ?? 0) + (data.trajectory["Deteriorating"] ?? 0), 0)}
          hint={`${data.trajectory["Rapidly Deteriorating"] ?? 0} rapidly · avg data confidence ${fmtNum(k.avg_data_confidence, 0)}/100`} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card title="Risk status (ongoing)" subtitle="RAG from calibrated early warnings + composite risk"><EChart option={charts.rag} height={240} /></Card>
        <Card title="Risk trajectory" subtitle="Direction of risk movement over the last 6 months"><EChart option={charts.traj} height={240} /></Card>
        <Card title="Early warnings by horizon" subtitle="Projects warned at each lead time"><EChart option={charts.warn} height={240} /></Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-3" title="Risk × momentum matrix"
          subtitle="Static risk vs trajectory: top-right = high and rising. Bubble size = revised cost. Click a project to open it.">
          <EChart option={charts.matrix} height={340} onClick={(p) => navigate(`/projects/${(p.data as string[])[3]}`)} />
        </Card>
        <div className="space-y-4 lg:col-span-2">
          <Card title="Average portfolio risk" subtitle="Ongoing projects, last 24 months"><EChart option={charts.hist} height={140} /></Card>
          <Card title="Warnings by risk dimension"><EChart option={charts.dims} height={130} /></Card>
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2" title="Priority attention list" subtitle="Ranked by Priority Attention Index (severity, momentum, financial exposure, urgency)"
          actions={<Link to="/projects" className="text-xs font-medium text-brand-600 hover:underline">All projects →</Link>} bodyClass="p-0">
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead><tr><th>Project</th><th>Status</th><th>Trajectory</th><th className="text-right">Risk</th><th className="text-right">Priority</th></tr></thead>
              <tbody>
                {data.top_priority.map((p) => (
                  <tr key={p.project_id} className="cursor-pointer" onClick={() => navigate(`/projects/${p.project_id}`)}>
                    <td><div className="line-clamp-2 font-medium text-slate-900" title={p.project_name}>{p.project_name}</div><div className="muted">{p.project_id} · {p.ministry}</div></td>
                    <td><RagBadge rag={p.rag} /></td>
                    <td><TrajBadge t={p.trajectory} /></td>
                    <td className="text-right tabular-nums">{fmtNum(p.risk_composite)}</td>
                    <td className="text-right font-semibold tabular-nums">{fmtNum(p.priority_index)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <div className="space-y-4">
        <LiveActivity />
        <Card title={<span className="flex items-center gap-1.5"><Lightbulb className="h-4 w-4 text-saffron" /> Systemic patterns</span>}
          subtitle="Computed from portfolio statistics (no LLM)">
          <ul className="space-y-3 text-sm leading-relaxed text-slate-700">
            {data.patterns.map((p, i) => <li key={i} className="border-l-2 border-brand-100 pl-3">{p}</li>)}
          </ul>
        </Card>
        </div>
      </div>
    </>
  );
}
