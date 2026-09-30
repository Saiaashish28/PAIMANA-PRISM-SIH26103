import { Link } from "react-router-dom";
import { EChart } from "../components/EChart";
import { Card, ErrorBox, Loading, PageHeader } from "../components/ui";
import { useApi } from "../lib/api";
import { DIM_COLOR, fmtNum, fmtPct } from "../lib/format";

interface Fp {
  name: string; projects: number; ongoing: number; completed: number; avg_risk: number; avg_cost_risk: number; avg_schedule_risk: number;
  avg_implementation_risk: number; red: number; amber: number; deteriorating: number; cost_escalation_pct: number; median_slip: number; avg_velocity: number;
}
interface Ent { name: string; projects: number; ongoing: number; completed: number; avg_slip: number; avg_cost_growth: number; avg_risk: number; delayed_share: number; red: number }
interface Intel {
  issue_basis: "remarks" | "signals";
  bottleneck_frequency: { window_months: number; overall: { category: string; label: string; projects: number }[] };
  bottleneck_impact: { category: string; label: string; n_reports: number; cost_lift: number; schedule_lift: number; stall_lift: number; cost_event_rate: number; schedule_event_rate: number }[];
  recurring: { project_id: string; project_name: string; ministry: string; label: string; months_unresolved: number }[];
  by_ministry: Fp[]; by_sector: Fp[];
  agencies: Ent[]; contractors: Ent[];
  patterns: string[];
}

export default function IntelligencePage() {
  const { data, isLoading, error } = useApi<Intel>("/portfolio/intelligence");
  if (isLoading) return <Loading />;
  if (error || !data) return <ErrorBox error={error} />;
  const bf = data.bottleneck_frequency.overall;
  const imp = data.bottleneck_impact;
  const mins = data.by_ministry.filter((m) => m.ongoing > 0);

  return (
    <>
      <PageHeader title="Systemic patterns" subtitle="From project analysis to systemic insight: which delivery issues are widespread, which ones precede overruns, where risk concentrates and which issues become chronic." />
      {data.issue_basis === "signals" && (
        <div className="mb-4 rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800">
          The Flash Reports carry no free-text remarks, so issues are <b>derived from the reported figures</b>: stalled progress,
          overdue completion, recent schedule or cost revisions, spending ahead of progress, and falling far behind the original plan.
          With remark-bearing exports, PRISM classifies the remarks (land, clearances, contractor, funding, …) instead.
        </div>
      )}
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title={`Most widespread issues (last ${data.bottleneck_frequency.window_months} months)`}
          subtitle={data.issue_basis === "signals" ? "Projects showing each issue signal in any month" : "Projects reporting each category, extracted from free-text remarks"}>
          <EChart height={300} option={{
            tooltip: {}, grid: { left: 210, right: 40, top: 10, bottom: 20 },
            xAxis: { type: "value", splitNumber: 4, axisLabel: { hideOverlap: true }, splitLine: { lineStyle: { color: "#f1f5f9" } } },
            yAxis: { type: "category", inverse: true, data: bf.map((b) => b.label) },
            series: [{ type: "bar", data: bf.map((b) => b.projects), itemStyle: { color: "#1e40af", borderRadius: 4 }, label: { show: true, position: "right" }, barWidth: 14 }],
          }} />
        </Card>
        <Card title="Which issues precede overruns?" subtitle="How much more likely a cost escalation, slip or stall is in the next 6 months when the issue is present, vs months without any issue (1.0 = no effect)">
          <EChart height={300} option={{
            tooltip: { trigger: "axis" }, legend: { top: 0 }, grid: { left: 210, right: 20, top: 30, bottom: 20 },
            xAxis: { type: "value", splitLine: { lineStyle: { color: "#f1f5f9" } } },
            yAxis: { type: "category", inverse: true, data: imp.map((b) => b.label) },
            series: [
              { name: "Cost escalation", type: "bar", data: imp.map((b) => b.cost_lift), itemStyle: { color: DIM_COLOR.cost } },
              { name: "Schedule slip", type: "bar", data: imp.map((b) => b.schedule_lift), itemStyle: { color: DIM_COLOR.schedule } },
              { name: "Stall", type: "bar", data: imp.map((b) => b.stall_lift), itemStyle: { color: DIM_COLOR.implementation },
                markLine: { silent: true, symbol: "none", data: [{ xAxis: 1 }], lineStyle: { color: "#475569", type: "dashed" } } },
            ],
          }} />
        </Card>
      </div>

      <Card className="mt-4" title="Ministry risk heatmap" subtitle="Average model risk (0-100) of ongoing projects by dimension">
        <EChart height={Math.max(300, mins.length * 26 + 60)} option={{
          tooltip: { formatter: (p: { value: [number, number, number] }) => `${mins[p.value[1]].name}<br/>${["Cost", "Schedule", "Implementation", "Composite"][p.value[0]]}: ${p.value[2].toFixed(1)}` },
          grid: { left: 210, right: 80, top: 30, bottom: 20 },
          xAxis: { type: "category", data: ["Cost", "Schedule", "Implementation", "Composite"], position: "top", splitArea: { show: true } },
          yAxis: { type: "category", data: mins.map((m) => m.name), inverse: true },
          visualMap: { min: 0, max: 70, calculable: true, orient: "vertical", right: 0, top: "middle", inRange: { color: ["#f0fdf4", "#fde68a", "#f97316", "#b91c1c"] } },
          series: [{
            type: "heatmap", label: { show: true, formatter: (p: { value: number[] }) => p.value[2].toFixed(0) },
            data: mins.flatMap((m, i) => [[0, i, m.avg_cost_risk], [1, i, m.avg_schedule_risk], [2, i, m.avg_implementation_risk], [3, i, m.avg_risk]]),
          }],
        }} />
      </Card>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card title="Sector fingerprints" subtitle="Typical risk pattern per sector" bodyClass="p-0">
          <div className="max-h-96 overflow-auto">
            <table className="tbl">
              <thead><tr><th>Sector</th><th className="text-right">Ongoing</th><th className="text-right">Avg risk</th><th className="text-right">Red</th><th className="text-right">Deteriorating</th><th className="text-right">Cost esc.</th><th className="text-right">Median slip</th></tr></thead>
              <tbody>
                {data.by_sector.map((s) => (
                  <tr key={s.name}><td>{s.name}</td><td className="text-right">{s.ongoing}</td><td className="text-right tabular-nums">{fmtNum(s.avg_risk)}</td><td className="text-right text-red-600">{s.red}</td>
                    <td className="text-right">{s.deteriorating}</td><td className="text-right tabular-nums">{fmtPct(s.cost_escalation_pct)}</td><td className="text-right tabular-nums">{fmtNum(s.median_slip, 0)} mo</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <Card title={data.contractors.length ? "Contractor benchmarking" : "Implementing agency benchmarking"}
          subtitle={`${data.contractors.length ? "Contractors" : "Agencies"} with 2+ projects, ranked by average risk`} bodyClass="p-0">
          <div className="max-h-96 overflow-auto">
            <table className="tbl">
              <thead><tr><th>{data.contractors.length ? "Contractor" : "Agency"}</th><th className="text-right">Projects</th><th className="text-right">Avg risk</th><th className="text-right">Delayed</th><th className="text-right">Avg slip</th><th className="text-right">Avg cost growth</th></tr></thead>
              <tbody>
                {(data.contractors.length ? data.contractors : data.agencies).slice(0, 50).map((c) => (
                  <tr key={c.name}><td className="max-w-xs">{c.name}</td><td className="text-right">{c.projects}</td><td className="text-right tabular-nums">{fmtNum(c.avg_risk)}</td>
                    <td className="text-right tabular-nums">{fmtPct(c.delayed_share, 0)}</td><td className="text-right tabular-nums">{fmtNum(c.avg_slip, 0)} mo</td><td className="text-right tabular-nums">{fmtPct(c.avg_cost_growth)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <Card className="mt-4" title={`Chronic issues (${data.recurring.length} projects)`} subtitle="Ongoing projects showing the same issue for 4+ consecutive months" bodyClass="p-0">
        <div className="max-h-96 overflow-auto">
          <table className="tbl">
            <thead><tr><th>Project</th><th>Ministry</th><th>Bottleneck</th><th className="text-right">Months unresolved</th></tr></thead>
            <tbody>
              {data.recurring.slice(0, 200).map((r) => (
                <tr key={r.project_id}><td><Link className="font-medium text-brand-700 hover:underline" to={`/projects/${r.project_id}`}>{r.project_name}</Link><div className="muted">{r.project_id}</div></td>
                  <td>{r.ministry}</td><td>{r.label}</td><td className="text-right font-semibold">{r.months_unresolved}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
