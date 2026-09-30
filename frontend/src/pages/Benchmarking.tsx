import { useMemo, useState } from "react";
import { EChart } from "../components/EChart";
import { Card, ErrorBox, ExportButton, Loading, PageHeader, Segmented } from "../components/ui";
import { useApi } from "../lib/api";
import { downloadCsv } from "../lib/csv";
import { fmtCr, fmtMonth, fmtNum, fmtPct } from "../lib/format";

type By = "ministry" | "sector" | "state" | "implementing_agency";
interface Row {
  name: string; ongoing: number; completed: number | null; original_cost_cr: number; revised_cost_cr: number; expenditure_cr: number;
  cost_escalation_pct: number; spend_pct: number; median_slip_months: number; delayed_pct: number; cost_overrun_pct_projects: number;
  avg_progress: number; avg_gap_vs_plan: number; avg_risk: number; red: number; deteriorating: number; avg_data_confidence: number;
  completed_final_cost_growth: number | null; completed_final_slip: number | null;
}
interface Resp { by: By; label: string; reference: Record<string, number>; rows: Row[]; trend: { name: string; report_month: string; cost_escalation_pct: number; slip: number }[] }

const METRICS: { key: keyof Row; label: string; unit: string; ref?: string; higherIsWorse: boolean }[] = [
  { key: "cost_escalation_pct", label: "Cost escalation", unit: "%", ref: "cost_escalation_pct", higherIsWorse: true },
  { key: "delayed_pct", label: "Projects delayed", unit: "%", ref: "delayed_pct", higherIsWorse: true },
  { key: "median_slip_months", label: "Median slippage", unit: " mo", ref: "median_slip_months", higherIsWorse: true },
  { key: "avg_risk", label: "Average model risk", unit: "", ref: "avg_risk", higherIsWorse: true },
  { key: "avg_progress", label: "Average progress", unit: "%", ref: "avg_progress", higherIsWorse: false },
  { key: "revised_cost_cr", label: "Revised cost", unit: " Cr", higherIsWorse: false },
];

export default function BenchmarkingPage() {
  const [by, setBy] = useState<By>("ministry");
  const [metric, setMetric] = useState<keyof Row>("cost_escalation_pct");
  const { data, isLoading, error } = useApi<Resp>(`/benchmark?by=${by}`);
  const m = METRICS.find((x) => x.key === metric)!;

  const sorted = useMemo(() => (data?.rows ?? []).slice().sort((a, b) => (b[metric] as number) - (a[metric] as number)).slice(0, 25), [data, metric]);
  const trendNames = useMemo(() => [...new Set((data?.trend ?? []).map((t) => t.name))], [data]);
  const trendMonths = useMemo(() => [...new Set((data?.trend ?? []).map((t) => t.report_month))].sort(), [data]);

  return (
    <>
      <PageHeader title="Benchmarking & comparative analytics"
        subtitle="Compare ministries, sectors, states and implementing agencies on escalation, delay, progress and predicted risk. The dashed line marks the portfolio-wide value."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Segmented value={by} onChange={setBy} options={[
              { key: "ministry", label: "Ministry" }, { key: "sector", label: "Sector" }, { key: "state", label: "State" },
              { key: "implementing_agency", label: "Agency" }]} />
            {data && <ExportButton onClick={() => downloadCsv(`prism_benchmark_${by}.csv`, data.rows as unknown as Record<string, unknown>[])} />}
          </div>
        } />
      {isLoading ? <Loading /> : error || !data ? <ErrorBox error={error} /> : (
        <>
          <Card title={`${m.label} by ${data.label.toLowerCase()}`} subtitle={`Top ${sorted.length} of ${data.rows.length} groups with at least 3 ongoing projects`}
            actions={<select className="input" value={metric as string} onChange={(e) => setMetric(e.target.value as keyof Row)}>
              {METRICS.map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}</select>}>
            <EChart height={Math.max(260, sorted.length * 24 + 50)} option={{
              tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
              grid: { left: 260, right: 60, top: 10, bottom: 20 },
              xAxis: { type: "value", splitLine: { lineStyle: { color: "#f1f5f9" } } },
              yAxis: { type: "category", inverse: true, data: sorted.map((r) => r.name), axisLabel: { width: 250, overflow: "truncate" } },
              series: [{
                type: "bar", barWidth: 14, label: { show: true, position: "right", formatter: (p: { value: number }) => fmtNum(p.value, 1) },
                data: sorted.map((r) => {
                  const v = r[metric] as number;
                  const ref = m.ref ? data.reference[m.ref] : undefined;
                  const bad = ref !== undefined && (m.higherIsWorse ? v > ref : v < ref);
                  return { value: v, itemStyle: { color: ref === undefined ? "#1e40af" : bad ? "#dc2626" : "#16a34a", borderRadius: 3 } };
                }),
                markLine: m.ref ? { symbol: "none", lineStyle: { type: "dashed", color: "#475569" }, label: { formatter: "portfolio" },
                  data: [{ xAxis: data.reference[m.ref] }] } : undefined,
              }],
            }} />
          </Card>

          {trendMonths.length > 2 && (
            <Card className="mt-4" title="Cost escalation over time" subtitle="Eight largest groups by revised cost">
              <EChart height={300} option={{
                tooltip: { trigger: "axis" }, legend: { type: "scroll", top: 0 }, grid: { left: 50, right: 20, top: 40, bottom: 30 },
                xAxis: { type: "category", data: trendMonths.map(fmtMonth) }, yAxis: { type: "value", name: "%", splitLine: { lineStyle: { color: "#f1f5f9" } } },
                series: trendNames.map((n) => ({ name: n, type: "line", symbol: "none",
                  data: trendMonths.map((mo) => data.trend.find((t) => t.name === n && t.report_month === mo)?.cost_escalation_pct ?? null) })),
              }} />
            </Card>
          )}

          <Card className="mt-4" title="Comparison table" bodyClass="p-0">
            <div className="max-h-[60vh] overflow-auto">
              <table className="tbl">
                <thead><tr><th>{data.label}</th><th className="text-right">Ongoing</th><th className="text-right">Revised cost</th><th className="text-right">Escalation</th>
                  <th className="text-right">Spent</th><th className="text-right">Delayed</th><th className="text-right">Median slip</th><th className="text-right">Avg progress</th>
                  <th className="text-right">Avg risk</th><th className="text-right">Red</th><th className="text-right">Completed: final escalation / slip</th></tr></thead>
                <tbody>
                  {data.rows.map((r) => (
                    <tr key={r.name}>
                      <td className="max-w-xs font-medium text-slate-800">{r.name}</td>
                      <td className="text-right">{r.ongoing}</td><td className="text-right tabular-nums">{fmtCr(r.revised_cost_cr)}</td>
                      <td className="text-right tabular-nums">{fmtPct(r.cost_escalation_pct)}</td><td className="text-right tabular-nums">{fmtPct(r.spend_pct, 0)}</td>
                      <td className="text-right tabular-nums">{fmtPct(r.delayed_pct, 0)}</td><td className="text-right tabular-nums">{fmtNum(r.median_slip_months, 0)} mo</td>
                      <td className="text-right tabular-nums">{fmtPct(r.avg_progress, 0)}</td><td className="text-right tabular-nums">{fmtNum(r.avg_risk)}</td>
                      <td className="text-right text-red-600">{r.red}</td>
                      <td className="text-right tabular-nums">{r.completed ? `${fmtPct(r.completed_final_cost_growth)} / ${fmtNum(r.completed_final_slip, 0)} mo (n=${r.completed})` : "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </>
  );
}
