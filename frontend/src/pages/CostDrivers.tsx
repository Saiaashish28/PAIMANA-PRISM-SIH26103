import { Link } from "react-router-dom";
import { EChart } from "../components/EChart";
import { Card, ErrorBox, ExportButton, Kpi, Loading, PageHeader } from "../components/ui";
import { useApi } from "../lib/api";
import { downloadCsv } from "../lib/csv";
import { fmtCr, fmtNum, fmtPct } from "../lib/format";

interface Share { name: string; overrun_cr: number; share_pct: number; projects: number }
interface Resp {
  total_overrun_cr: number; projects_with_overrun: number; projects_for_80pct: number;
  by_ministry: Share[]; by_sector: Share[]; by_state: Share[];
  pareto: { project_id: string; project_name: string; ministry: string; original_cost_cr: number; revised_cost_cr: number; overrun_cr: number; cost_growth_pct: number; slip_months: number; cum_share: number }[];
  time_cost_link: { delay_band: string; projects: number; mean_cost_growth: number | null; median_cost_growth: number | null; share_with_overrun: number | null }[];
  regression: null | { n: number; r2: number; note: string; baseline_sector: string[]; coefficients: { term: string; coef: number; ci_low: number; ci_high: number; p_value: number; significant: boolean }[] };
  model_drivers: { feature: string; label: string; share_pct: number; non_cuf: boolean }[];
}

function ShareChart({ rows }: { rows: Share[] }) {
  return <EChart height={Math.max(220, rows.length * 24 + 40)} option={{
    tooltip: { formatter: (p: { name: string; value: number; dataIndex: number }) => `${p.name}<br/>${fmtCr(p.value)} · ${rows[p.dataIndex].share_pct}% of overrun · ${rows[p.dataIndex].projects} projects` },
    grid: { left: 230, right: 60, top: 10, bottom: 20 },
    xAxis: { type: "value", axisLabel: { formatter: (v: number) => `${(v / 1000).toFixed(0)}k` }, splitLine: { lineStyle: { color: "#f1f5f9" } } },
    yAxis: { type: "category", inverse: true, data: rows.map((r) => r.name), axisLabel: { width: 220, overflow: "truncate" } },
    series: [{ type: "bar", barWidth: 13, data: rows.map((r) => r.overrun_cr), itemStyle: { color: "#7c3aed", borderRadius: 3 },
      label: { show: true, position: "right", formatter: (p: { dataIndex: number }) => `${rows[p.dataIndex].share_pct}%` } }],
  }} />;
}

export default function CostDriversPage() {
  const { data, isLoading, error } = useApi<Resp>("/drivers/cost");
  if (isLoading) return <Loading />;
  if (error || !data) return <ErrorBox error={error} />;
  const reg = data.regression;
  return (
    <>
      <PageHeader title="Cost escalation driver analysis"
        subtitle="Where the portfolio's cost overrun sits, how it relates to delay, and which factors the models and a statistical regression associate with escalation." />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="Total cost overrun" tone="red" value={fmtCr(data.total_overrun_cr)} hint="revised minus original cost, ongoing projects" />
        <Kpi label="Projects with overrun" value={fmtNum(data.projects_with_overrun, 0)} />
        <Kpi label="Concentration" tone="amber" value={fmtNum(data.projects_for_80pct, 0)} hint="projects account for 80% of the overrun" />
        <Kpi label="Regression fit" value={reg ? `R² ${reg.r2}` : "–"} hint={reg ? `OLS on ${reg.n} projects` : "not enough data"} />
      </div>
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card title="Overrun by ministry / department"><ShareChart rows={data.by_ministry} /></Card>
        <Card title="Overrun by sector"><ShareChart rows={data.by_sector} /></Card>
      </div>
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card title="Delay and cost go together" subtitle="Average cost growth and share of projects with an overrun, by schedule slippage band (project count in brackets)">
          <EChart height={280} option={{
            tooltip: { trigger: "axis" }, legend: { top: 0 }, grid: { left: 50, right: 50, top: 40, bottom: 30 },
            xAxis: { type: "category", data: data.time_cost_link.map((r) => `${r.delay_band}\n(${r.projects})`), axisLabel: { interval: 0 } },
            yAxis: [{ type: "value", name: "avg %", splitLine: { lineStyle: { color: "#f1f5f9" } } }, { type: "value", name: "share %", max: 100 }],
            series: [
              { name: "Average cost growth %", type: "bar", data: data.time_cost_link.map((r) => r.mean_cost_growth?.toFixed(1)), color: "#7c3aed", barMaxWidth: 36 },
              { name: "Projects with overrun %", type: "line", yAxisIndex: 1, data: data.time_cost_link.map((r) => r.share_with_overrun), color: "#dc2626" },
            ],
          }} />
        </Card>
        <Card title="Model drivers of cost escalation (12-month model, mean |SHAP|)" subtitle="◆ = variable not in the CUF">
          <EChart height={280} option={{
            tooltip: {}, grid: { left: 260, right: 40, top: 10, bottom: 20 },
            xAxis: { type: "value", splitNumber: 3, axisLabel: { formatter: "{value}%" }, splitLine: { lineStyle: { color: "#f1f5f9" } } },
            yAxis: { type: "category", inverse: true, data: data.model_drivers.slice(0, 10).map((d) => `${d.non_cuf ? "◆ " : ""}${d.label}`) },
            series: [{ type: "bar", barWidth: 12, data: data.model_drivers.slice(0, 10).map((d) => ({ value: d.share_pct, itemStyle: { color: d.non_cuf ? "#f59e0b" : "#1e40af", borderRadius: 3 } })) }],
          }} />
        </Card>
      </div>
      {reg && (
        <Card className="mt-4" title="Statistical driver model (statsmodels OLS)"
          subtitle={`${reg.note}${reg.baseline_sector?.length ? ` Sector effects are relative to ${reg.baseline_sector[0]}.` : ""}`} bodyClass="p-0">
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead><tr><th>Factor</th><th className="text-right">Effect on cost growth (pp)</th><th className="text-right">95% CI</th><th className="text-right">p</th><th /></tr></thead>
              <tbody>
                {reg.coefficients.map((c) => (
                  <tr key={c.term}><td>{c.term}</td><td className="text-right font-semibold tabular-nums">{c.coef > 0 ? "+" : ""}{fmtNum(c.coef, 2)}</td>
                    <td className="text-right tabular-nums">[{fmtNum(c.ci_low, 2)}, {fmtNum(c.ci_high, 2)}]</td><td className="text-right tabular-nums">{c.p_value < 0.001 ? "<0.001" : fmtNum(c.p_value, 3)}</td>
                    <td>{c.significant && <span className="chip bg-brand-50 text-brand-700">significant</span>}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      <Card className="mt-4" title="Projects driving the overrun (Pareto)" bodyClass="p-0"
        actions={<ExportButton onClick={() => downloadCsv("prism_cost_overrun_pareto.csv", data.pareto as unknown as Record<string, unknown>[])} />}>
        <div className="max-h-[60vh] overflow-auto">
          <table className="tbl">
            <thead><tr><th>Project</th><th className="text-right">Original</th><th className="text-right">Revised</th><th className="text-right">Overrun</th><th className="text-right">Growth</th><th className="text-right">Slip</th><th className="text-right">Cumulative share</th></tr></thead>
            <tbody>
              {data.pareto.map((p) => (
                <tr key={p.project_id}>
                  <td><Link className="font-medium text-brand-700 hover:underline" to={`/projects/${p.project_id}`}>{p.project_name}</Link><div className="muted">{p.project_id} · {p.ministry}</div></td>
                  <td className="text-right tabular-nums">{fmtCr(p.original_cost_cr)}</td><td className="text-right tabular-nums">{fmtCr(p.revised_cost_cr)}</td>
                  <td className="text-right font-semibold tabular-nums">{fmtCr(p.overrun_cr)}</td><td className="text-right tabular-nums">{fmtPct(p.cost_growth_pct)}</td>
                  <td className="text-right tabular-nums">{p.slip_months} mo</td><td className="text-right tabular-nums">{fmtPct(p.cum_share, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
