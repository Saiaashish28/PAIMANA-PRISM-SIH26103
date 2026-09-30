import { useState } from "react";
import { EChart } from "../components/EChart";
import { Card, ErrorBox, Loading, PageHeader } from "../components/ui";
import { useApi } from "../lib/api";
import { DIM_LABEL, fmtNum } from "../lib/format";

interface Cls { dimension: string; horizon: number; model: string; auc: number; pr_auc: number; brier: number; precision: number; recall: number; base_rate: number; n_test: number; threshold: number }
interface Sig { dimension: string; horizon: number; auc_diff: number; ci_low: number; ci_high: number; p_value: number; significant: boolean }
interface Cuf {
  dimension: string; horizon: number; cuf_only_auc: number; cuf_plus_noncuf_auc: number; uplift: number; ci_low: number; ci_high: number; p_value: number;
  significant: boolean; early_stage_cuf_only_auc: number | null; early_stage_full_auc: number | null; early_stage_n: number;
}
interface Lead { dimension: string; model: string; n_events: number; detection_rate: number; median_lead_months: number | null; mean_lead_months: number | null; false_alarm_rate: number | null }
interface Reg { target: string; unit: string; ml_mae: number; ols_mae: number; naive_mae: number; interval_coverage_80: number; n_test_rows: number }
interface Imp { feature: string; label: string; importance?: number; share_pct?: number; non_cuf: boolean }
interface Bench {
  classification: Cls[]; significance: Sig[]; cuf_sufficiency: Cuf[]; lead_times: Lead[]; regression: Reg[];
  permutation_importance: Record<string, Imp[]>; global_shap: Record<string, Imp[]>; split: Record<string, number>;
}

const MODELS = ["XGBoost", "HistGradientBoosting", "Logistic regression (statistical baseline)"];
const MCOL = ["#1e40af", "#0d9488", "#94a3b8"];
const key = (d: string, h: number) => `${DIM_LABEL[d].split(" ")[0]} · ${h}m`;

export default function BenchmarkPage() {
  const { data, isLoading, error } = useApi<Bench>("/models/benchmark");
  const [dim, setDim] = useState("cost");
  if (isLoading) return <Loading />;
  if (error || !data) return <ErrorBox error={error} />;
  const cats = [...new Map(data.classification.map((c) => [key(c.dimension, c.horizon), c])).keys()];
  const metric = (m: string, f: keyof Cls) => cats.map((k) => data.classification.find((c) => key(c.dimension, c.horizon) === k && c.model === m)?.[f] as number);
  const shap = data.global_shap[`${dim}_6`] ?? [];
  const perm = data.permutation_importance[dim] ?? [];

  return (
    <>
      <PageHeader title="Model benchmark: AI/ML vs conventional statistics"
        subtitle={`Held-out evaluation on ${data.split.test} unseen projects (models trained on ${data.split.train}, alert thresholds calibrated on ${data.split.calib}). Projects never cross splits.`} />

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Discrimination (ROC-AUC) on held-out projects" subtitle="Early-warning classifiers for each risk dimension and horizon">
          <EChart height={320} option={{
            tooltip: { trigger: "axis" }, legend: { top: 0 }, grid: { left: 40, right: 10, top: 40, bottom: 50 },
            xAxis: { type: "category", data: cats, axisLabel: { rotate: 30 } },
            yAxis: { type: "value", min: 0.5, max: 1, splitLine: { lineStyle: { color: "#f1f5f9" } } },
            series: MODELS.map((m, i) => ({ name: m.replace(" (statistical baseline)", ""), type: "bar", data: metric(m, "auc"), itemStyle: { color: MCOL[i] } })),
          }} />
        </Card>
        <Card title="Precision-recall AUC" subtitle="More informative than ROC for rarer events such as 3-month cost escalations">
          <EChart height={320} option={{
            tooltip: { trigger: "axis" }, legend: { top: 0 }, grid: { left: 40, right: 10, top: 40, bottom: 50 },
            xAxis: { type: "category", data: cats, axisLabel: { rotate: 30 } },
            yAxis: { type: "value", min: 0, max: 1, splitLine: { lineStyle: { color: "#f1f5f9" } } },
            series: [
              ...MODELS.map((m, i) => ({ name: m.replace(" (statistical baseline)", ""), type: "bar", data: metric(m, "pr_auc"), itemStyle: { color: MCOL[i] } })),
              { name: "Base rate", type: "scatter", symbol: "rect", symbolSize: [18, 3], data: metric("XGBoost", "base_rate"), itemStyle: { color: "#dc2626" } },
            ],
          }} />
        </Card>
      </div>

      <Card className="mt-4" title="Is the ML gain statistically significant?" bodyClass="p-0"
        subtitle="XGBoost − logistic regression ROC-AUC, 95% CI from a project-clustered bootstrap (200 resamples)">
        <div className="overflow-x-auto">
          <table className="tbl">
            <thead><tr><th>Dimension</th><th>Horizon</th><th className="text-right">XGB AUC</th><th className="text-right">Logit AUC</th><th className="text-right">Δ AUC</th><th className="text-right">95% CI</th><th className="text-right">p</th><th>Verdict</th></tr></thead>
            <tbody>
              {data.significance.map((s) => {
                const x = data.classification.find((c) => c.dimension === s.dimension && c.horizon === s.horizon && c.model === MODELS[0]);
                const l = data.classification.find((c) => c.dimension === s.dimension && c.horizon === s.horizon && c.model === MODELS[2]);
                return (
                  <tr key={`${s.dimension}${s.horizon}`}>
                    <td>{DIM_LABEL[s.dimension]}</td><td>{s.horizon} months</td>
                    <td className="text-right tabular-nums">{fmtNum(x?.auc, 3)}</td><td className="text-right tabular-nums">{fmtNum(l?.auc, 3)}</td>
                    <td className="text-right font-semibold tabular-nums">{s.auc_diff > 0 ? "+" : ""}{fmtNum(s.auc_diff, 3)}</td>
                    <td className="text-right tabular-nums">[{fmtNum(s.ci_low, 3)}, {fmtNum(s.ci_high, 3)}]</td>
                    <td className="text-right tabular-nums">{fmtNum(s.p_value, 2)}</td>
                    <td>{s.significant ? <span className="chip bg-green-100 text-green-700">ML significantly better</span> : <span className="chip bg-slate-100 text-slate-600">No significant difference</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card title="Early-warning lead time" subtitle="12-month models on held-out projects: share of actual revisions flagged in advance, and how early" bodyClass="p-0">
          <table className="tbl">
            <thead><tr><th>Event</th><th>Model</th><th className="text-right">Events</th><th className="text-right">Detected</th><th className="text-right">Mean lead</th><th className="text-right">False-alarm rate</th></tr></thead>
            <tbody>
              {data.lead_times.map((l, i) => (
                <tr key={i}><td>{l.dimension === "cost" ? "Cost revision" : "Schedule revision"}</td><td>{l.model.replace(" (statistical baseline)", "")}</td>
                  <td className="text-right">{l.n_events}</td><td className="text-right tabular-nums">{fmtNum(l.detection_rate * 100, 0)}%</td>
                  <td className="text-right tabular-nums">{fmtNum(l.mean_lead_months)} mo</td><td className="text-right tabular-nums">{l.false_alarm_rate === null ? "–" : `${fmtNum(l.false_alarm_rate * 100, 0)}%`}</td></tr>
              ))}
            </tbody>
          </table>
        </Card>
        <Card title="Cost & time overrun regression" subtitle="Predicting the final outcome of ongoing projects (held-out completed projects)" bodyClass="p-0">
          <table className="tbl">
            <thead><tr><th>Target</th><th className="text-right">Quantile GBM MAE</th><th className="text-right">OLS (statsmodels) MAE</th><th className="text-right">Naive MAE</th><th className="text-right">80% interval coverage</th></tr></thead>
            <tbody>
              {data.regression.map((r) => (
                <tr key={r.target}><td>{r.target}</td><td className="text-right font-semibold tabular-nums">{fmtNum(r.ml_mae, 2)}</td><td className="text-right tabular-nums">{fmtNum(r.ols_mae, 2)}</td>
                  <td className="text-right tabular-nums">{fmtNum(r.naive_mae, 2)}</td><td className="text-right tabular-nums">{fmtNum(r.interval_coverage_80 * 100, 0)}%</td></tr>
              ))}
            </tbody>
          </table>
          <p className="muted px-4 py-2">Naive = assume no further growth beyond what is already reported.</p>
        </Card>
      </div>

      <Card className="mt-4" title="CUF sufficiency: do non-CUF variables add predictive value?"
        subtitle="Same split, same algorithm: CUF fields only vs CUF + non-CUF variables — the track record of the same implementing agency, state and sector on other projects (derived point-in-time), plus external variables such as contractor credit or cost inflation when supplied" bodyClass="p-0">
        <div className="overflow-x-auto">
          <table className="tbl">
            <thead><tr><th>Dimension</th><th>Horizon</th><th className="text-right">CUF-only AUC</th><th className="text-right">CUF + non-CUF AUC</th><th className="text-right">Uplift [95% CI]</th><th className="text-right">Early-stage (&lt;35% elapsed) CUF → +non-CUF</th><th>Verdict</th></tr></thead>
            <tbody>
              {data.cuf_sufficiency.map((c) => (
                <tr key={`${c.dimension}${c.horizon}`}>
                  <td>{DIM_LABEL[c.dimension]}</td><td>{c.horizon} months</td>
                  <td className="text-right tabular-nums">{fmtNum(c.cuf_only_auc, 3)}</td><td className="text-right tabular-nums">{fmtNum(c.cuf_plus_noncuf_auc, 3)}</td>
                  <td className="text-right tabular-nums">{c.uplift > 0 ? "+" : ""}{fmtNum(c.uplift, 3)} [{fmtNum(c.ci_low, 3)}, {fmtNum(c.ci_high, 3)}]</td>
                  <td className="text-right tabular-nums">{c.early_stage_cuf_only_auc === null ? "–" : `${fmtNum(c.early_stage_cuf_only_auc, 3)} → ${fmtNum(c.early_stage_full_auc, 3)}`}</td>
                  <td>{c.significant ? <span className="chip bg-green-100 text-green-700">Significant uplift</span> : <span className="chip bg-slate-100 text-slate-600">CUF sufficient</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card title="Global drivers (mean |SHAP|, 6-month model)" subtitle="◆ marks non-CUF variables"
          actions={<select className="input" value={dim} onChange={(e) => setDim(e.target.value)}>{["cost", "schedule", "implementation"].map((d) => <option key={d} value={d}>{DIM_LABEL[d]}</option>)}</select>}>
          <EChart height={360} option={{
            tooltip: {}, grid: { left: 260, right: 40, top: 10, bottom: 20 },
            xAxis: { type: "value", axisLabel: { formatter: "{value}%" }, splitLine: { lineStyle: { color: "#f1f5f9" } } },
            yAxis: { type: "category", inverse: true, data: shap.slice(0, 12).map((s) => `${s.non_cuf ? "◆ " : ""}${s.label}`) },
            series: [{ type: "bar", barWidth: 12, data: shap.slice(0, 12).map((s) => ({ value: s.share_pct, itemStyle: { color: s.non_cuf ? "#f59e0b" : "#1e40af", borderRadius: 3 } })) }],
          }} />
        </Card>
        <Card title="Permutation importance (held-out AUC drop)" subtitle="Model-agnostic check of the SHAP ranking">
          <EChart height={360} option={{
            tooltip: {}, grid: { left: 260, right: 40, top: 10, bottom: 20 },
            xAxis: { type: "value", splitLine: { lineStyle: { color: "#f1f5f9" } } },
            yAxis: { type: "category", inverse: true, data: perm.slice(0, 12).map((s) => `${s.non_cuf ? "◆ " : ""}${s.label}`) },
            series: [{ type: "bar", barWidth: 12, data: perm.slice(0, 12).map((s) => ({ value: s.importance, itemStyle: { color: s.non_cuf ? "#f59e0b" : "#0d9488", borderRadius: 3 } })) }],
          }} />
        </Card>
      </div>
    </>
  );
}
