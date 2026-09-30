import { Link } from "react-router-dom";
import { EChart } from "../components/EChart";
import { Card, ErrorBox, Kpi, Loading, PageHeader } from "../components/ui";
import { useApi } from "../lib/api";
import { fmtMonth, fmtNum } from "../lib/format";

interface TrustResp {
  avg_confidence: number;
  grades: Record<string, number>;
  stale_projects: number;
  issue_rates: Record<string, number>;
  issue_labels: Record<string, string>;
  lowest_confidence: { project_id: string; project_name: string; ministry: string; status: string; data_confidence: number; confidence_grade: string; staleness_months: number; n_contradictions: number; n_anomalies: number; missingness_pct: number; last_report_month: string }[];
  recent_issues: { project_id: string; month: string; label: string; reported_progress: number | null; reported_expenditure: number | null; revised_cost: number }[];
}

export default function TrustPage() {
  const { data, isLoading, error } = useApi<TrustResp>("/trust");
  if (isLoading) return <Loading />;
  if (error || !data) return <ErrorBox error={error} />;
  const rates = Object.entries(data.issue_rates);
  return (
    <>
      <PageHeader title="Data trust engine" subtitle="Missing, stale, contradictory and anomalous CUF values are detected and cleaned before any risk prediction; each project carries a data-confidence score." />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="Avg data confidence" value={`${fmtNum(data.avg_confidence, 1)}/100`} tone="blue" />
        <Kpi label="High confidence" tone="green" value={data.grades.High ?? 0} hint="score ≥ 80" />
        <Kpi label="Low confidence" tone="red" value={data.grades.Low ?? 0} hint="score < 60 — verify before acting" />
        <Kpi label="Stale reporting" tone="amber" value={data.stale_projects} hint="ongoing projects missing recent months" />
      </div>
      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card title="Issue rates across all monthly snapshots">
          <EChart height={300} option={{
            tooltip: { valueFormatter: (v: number) => `${v.toFixed(2)}%` }, grid: { left: 220, right: 40, top: 10, bottom: 20 },
            xAxis: { type: "value", axisLabel: { formatter: "{value}%" }, splitLine: { lineStyle: { color: "#f1f5f9" } } },
            yAxis: { type: "category", inverse: true, data: rates.map(([k]) => data.issue_labels[k] ?? k) },
            series: [{ type: "bar", barWidth: 12, data: rates.map(([, v]) => +(v * 100).toFixed(2)), itemStyle: { color: "#f59e0b", borderRadius: 3 } }],
          }} />
        </Card>
        <Card className="xl:col-span-2" title="Lowest-confidence projects" bodyClass="p-0">
          <div className="max-h-80 overflow-auto">
            <table className="tbl">
              <thead><tr><th>Project</th><th className="text-right">Confidence</th><th className="text-right">Stale (mo)</th><th className="text-right">Contradictions</th><th className="text-right">Anomalies</th><th className="text-right">Missing</th><th>Last report</th></tr></thead>
              <tbody>
                {data.lowest_confidence.map((p) => (
                  <tr key={p.project_id}>
                    <td><Link className="font-medium text-brand-700 hover:underline" to={`/projects/${p.project_id}`}>{p.project_name}</Link><div className="muted">{p.project_id} · {p.status}</div></td>
                    <td className="text-right font-semibold tabular-nums">{fmtNum(p.data_confidence)}</td><td className="text-right">{p.staleness_months}</td>
                    <td className="text-right">{p.n_contradictions}</td><td className="text-right">{p.n_anomalies}</td><td className="text-right">{fmtNum(p.missingness_pct)}%</td>
                    <td>{fmtMonth(p.last_report_month)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
      <Card className="mt-4" title="Recently detected issues" bodyClass="p-0">
        <div className="max-h-96 overflow-auto">
          <table className="tbl">
            <thead><tr><th>Month</th><th>Project</th><th>Issue</th><th className="text-right">Reported progress</th><th className="text-right">Reported expenditure</th><th className="text-right">Revised cost</th></tr></thead>
            <tbody>
              {data.recent_issues.map((x, i) => (
                <tr key={i}><td>{fmtMonth(x.month)}</td><td><Link className="text-brand-700 hover:underline" to={`/projects/${x.project_id}`}>{x.project_id}</Link></td><td>{x.label}</td>
                  <td className="text-right tabular-nums">{x.reported_progress === null ? "missing" : `${fmtNum(x.reported_progress)}%`}</td>
                  <td className="text-right tabular-nums">{x.reported_expenditure === null ? "missing" : fmtNum(x.reported_expenditure)}</td>
                  <td className="text-right tabular-nums">{fmtNum(x.revised_cost)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
