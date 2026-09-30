import { EChart } from "../components/EChart";
import { Card, ErrorBox, ExportButton, Kpi, Loading, PageHeader } from "../components/ui";
import { useApi } from "../lib/api";
import { downloadCsv } from "../lib/csv";
import { fmtCr, fmtMonth, fmtNum, fmtPct } from "../lib/format";

interface Row {
  report_month: string; projects: number; original_cost_cr: number; revised_cost_cr: number; expenditure_cr: number;
  delayed: number; delayed_pct: number; cost_overrun_projects: number; avg_slip_months: number; avg_progress: number;
  avg_risk: number; cost_escalation_pct: number; report_missing: boolean;
}

const grid = { left: 56, right: 56, top: 36, bottom: 30 };
const split = { splitLine: { lineStyle: { color: "#f1f5f9" } } };

export default function TrendsPage() {
  const { data, isLoading, error } = useApi<Row[]>("/portfolio/trends");
  if (isLoading) return <Loading />;
  if (error || !data) return <ErrorBox error={error} />;
  const rows = data.filter((r) => !r.report_missing);
  const last = rows[rows.length - 1];
  const first = rows[0];
  const months = rows.map((r) => fmtMonth(r.report_month));
  const delta = (a: number, b: number) => (a - b >= 0 ? "+" : "") + fmtNum(a - b, 1);

  return (
    <>
      <PageHeader title="Portfolio trends"
        subtitle={`How the monitored portfolio evolved month by month (${fmtMonth(first?.report_month)} – ${fmtMonth(last?.report_month)}). Months without a report are omitted.`}
        actions={<ExportButton onClick={() => downloadCsv("prism_portfolio_trends.csv", data as unknown as Record<string, unknown>[])} />} />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="Ongoing projects" value={fmtNum(last?.projects, 0)} hint={`${delta(last?.projects, first?.projects)} since ${fmtMonth(first?.report_month)}`} />
        <Kpi label="Revised cost" value={fmtCr(last?.revised_cost_cr)} hint={`original ${fmtCr(last?.original_cost_cr)}`} />
        <Kpi label="Cost escalation" tone="amber" value={fmtPct(last?.cost_escalation_pct)} hint={`${delta(last?.cost_escalation_pct, first?.cost_escalation_pct)} pp over the period`} />
        <Kpi label="Delayed projects" tone="red" value={fmtPct(last?.delayed_pct, 0)} hint={`${fmtNum(last?.delayed, 0)} projects behind original schedule`} />
      </div>
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card title="Cost of the ongoing portfolio" subtitle="Original vs revised cost and cumulative expenditure (₹ crore)">
          <EChart height={300} option={{
            tooltip: { trigger: "axis" }, legend: { top: 0 }, grid,
            xAxis: { type: "category", data: months },
            yAxis: { type: "value", axisLabel: { formatter: (v: number) => `${(v / 1e5).toFixed(0)}L` }, ...split },
            series: [
              { name: "Original cost", type: "line", data: rows.map((r) => r.original_cost_cr), color: "#94a3b8", symbol: "none", lineStyle: { width: 2 } },
              { name: "Revised cost", type: "line", data: rows.map((r) => r.revised_cost_cr), color: "#7c3aed", symbol: "none", lineStyle: { width: 2.5 } },
              { name: "Expenditure", type: "line", data: rows.map((r) => r.expenditure_cr), color: "#0d9488", symbol: "none", areaStyle: { opacity: 0.08 } },
            ],
          }} />
        </Card>
        <Card title="Escalation and delay" subtitle="Portfolio cost escalation (%) and share of projects behind original schedule">
          <EChart height={300} option={{
            tooltip: { trigger: "axis" }, legend: { top: 0 }, grid,
            xAxis: { type: "category", data: months },
            yAxis: [{ type: "value", name: "escalation %", ...split }, { type: "value", name: "delayed %", max: 100 }],
            series: [
              { name: "Cost escalation %", type: "line", data: rows.map((r) => r.cost_escalation_pct.toFixed(2)), color: "#7c3aed", symbol: "circle", symbolSize: 5 },
              { name: "Delayed projects %", type: "bar", yAxisIndex: 1, data: rows.map((r) => r.delayed_pct.toFixed(1)), color: "#fca5a5", barMaxWidth: 18 },
            ],
          }} />
        </Card>
        <Card title="Size of the portfolio" subtitle="Ongoing projects and those with a cost overrun">
          <EChart height={260} option={{
            tooltip: { trigger: "axis" }, legend: { top: 0 }, grid,
            xAxis: { type: "category", data: months }, yAxis: { type: "value", ...split },
            series: [
              { name: "Ongoing projects", type: "bar", data: rows.map((r) => r.projects), color: "#1e40af", barMaxWidth: 18 },
              { name: "With cost overrun", type: "line", data: rows.map((r) => r.cost_overrun_projects), color: "#f59e0b" },
            ],
          }} />
        </Card>
        <Card title="Delivery and risk" subtitle="Average physical progress, average slippage (months) and average model risk">
          <EChart height={260} option={{
            tooltip: { trigger: "axis" }, legend: { top: 0 }, grid,
            xAxis: { type: "category", data: months }, yAxis: { type: "value", ...split },
            series: [
              { name: "Avg progress %", type: "line", data: rows.map((r) => r.avg_progress.toFixed(1)), color: "#0d9488" },
              { name: "Avg slippage (months)", type: "line", data: rows.map((r) => r.avg_slip_months.toFixed(1)), color: "#dc2626" },
              { name: "Avg risk (0-100)", type: "line", data: rows.map((r) => r.avg_risk.toFixed(1)), color: "#0f172a", lineStyle: { type: "dashed" } },
            ],
          }} />
        </Card>
      </div>
    </>
  );
}
