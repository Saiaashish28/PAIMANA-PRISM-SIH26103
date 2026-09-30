import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card, ErrorBox, ExportButton, Loading, PageHeader, RagBadge, SeverityBadge, TrajBadge } from "../components/ui";
import { downloadCsv } from "../lib/csv";
import { qs, useApi } from "../lib/api";
import { DIM_COLOR, fmtNum, fmtProb } from "../lib/format";
import type { Meta, Warning } from "../lib/types";

const TABS = [
  { h: 3, label: "3-month", desc: "Critical — event expected within a quarter" },
  { h: 6, label: "6-month", desc: "High — event expected within two quarters" },
  { h: 12, label: "12-month", desc: "Watch — event expected within a year" },
];

export default function WarningsPage() {
  const [h, setH] = useState(3);
  const [dim, setDim] = useState("");
  const [ministry, setMinistry] = useState("");
  const meta = useApi<Meta>("/meta");
  const all = useApi<Warning[]>("/warnings");
  const { data, isLoading, error } = useApi<Warning[]>(`/warnings${qs({ horizon: h, dimension: dim, ministry })}`);
  const navigate = useNavigate();
  const counts = (hz: number) => new Set((all.data ?? []).filter((w) => w.horizon_months === hz).map((w) => w.project_id)).size;

  return (
    <>
      <PageHeader title="Early warning system"
        subtitle="Calibrated probabilities of a cost escalation (≥5 pp), schedule slip (≥3 months) or implementation stall, raised at the shortest horizon that crosses its alert threshold." />
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        {TABS.map((t) => (
          <button key={t.h} onClick={() => setH(t.h)}
            className={`card p-4 text-left transition ${h === t.h ? "ring-2 ring-brand-600" : "hover:border-slate-300"}`}>
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold">{t.label} warnings</span>
              <SeverityBadge s={t.h === 3 ? "Critical" : t.h === 6 ? "High" : "Watch"} />
            </div>
            <div className="mt-2 text-3xl font-semibold tabular-nums">{counts(t.h)}</div>
            <div className="muted">{t.desc}</div>
          </button>
        ))}
      </div>
      <Card title={`${h}-month horizon`} bodyClass="p-0"
        actions={
          <div className="flex flex-wrap gap-2">
            <select className="input" value={dim} onChange={(e) => setDim(e.target.value)}>
              <option value="">All dimensions</option>
              <option value="cost">Cost overrun</option>
              <option value="schedule">Schedule slippage</option>
              <option value="implementation">Implementation stall</option>
            </select>
            <select className="input max-w-56" value={ministry} onChange={(e) => setMinistry(e.target.value)}>
              <option value="">All ministries</option>
              {meta.data?.ministries.map((m) => <option key={m}>{m}</option>)}
            </select>
            {data && <ExportButton onClick={() => downloadCsv(`prism_warnings_${h}m.csv`, data as unknown as Record<string, unknown>[])} />}
          </div>
        }>
        {isLoading ? <Loading /> : error ? <div className="p-4"><ErrorBox error={error} /></div> : (
          <div className="max-h-[65vh] overflow-auto">
            <table className="tbl">
              <thead><tr><th>Project</th><th>Warning</th><th>Probability vs threshold</th><th>Status</th><th>Trajectory</th><th className="text-right">Data conf.</th><th className="text-right">Priority</th></tr></thead>
              <tbody>
                {data?.map((w, i) => (
                  <tr key={i} className="cursor-pointer" onClick={() => navigate(`/projects/${w.project_id}`)}>
                    <td className="max-w-md"><div className="line-clamp-2 font-medium text-slate-900" title={w.project_name}>{w.project_name}</div><div className="muted">{w.project_id} · {w.ministry}</div></td>
                    <td>
                      <span className="chip" style={{ color: DIM_COLOR[w.dimension], background: `${DIM_COLOR[w.dimension]}14` }}>{w.warning}</span>
                      {w.source === "anomaly" && <div className="muted mt-1">anomaly rule</div>}
                    </td>
                    <td className="min-w-40">
                      {w.probability !== null ? (
                        <div>
                          <div className="flex justify-between text-xs"><span className="font-semibold">{fmtProb(w.probability)}</span><span className="muted">thr {fmtProb(w.threshold)}</span></div>
                          <div className="relative mt-1 h-1.5 rounded-full bg-slate-100">
                            <div className="h-1.5 rounded-full" style={{ width: `${w.probability * 100}%`, background: DIM_COLOR[w.dimension] }} />
                            <div className="absolute -top-0.5 h-2.5 w-0.5 bg-slate-700" style={{ left: `${(w.threshold ?? 0) * 100}%` }} />
                          </div>
                        </div>
                      ) : <span className="muted">velocity collapse vs own 6-month pace</span>}
                    </td>
                    <td>{w.rag && <RagBadge rag={w.rag} />}</td>
                    <td><TrajBadge t={w.trajectory} /></td>
                    <td className="text-right tabular-nums">{fmtNum(w.data_confidence, 0)}</td>
                    <td className="text-right font-semibold tabular-nums">{fmtNum(w.priority_index)}</td>
                  </tr>
                ))}
                {data?.length === 0 && <tr><td colSpan={7} className="p-6 text-center text-slate-500">No warnings for this filter.</td></tr>}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
