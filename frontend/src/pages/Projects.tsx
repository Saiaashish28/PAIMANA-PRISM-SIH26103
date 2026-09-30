import { ArrowDown, ArrowUp, Search } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bar, Card, ErrorBox, ExportButton, Loading, PageHeader, RagBadge, Select, TrajBadge } from "../components/ui";
import { api, qs, useApi } from "../lib/api";
import { downloadCsv } from "../lib/csv";
import { fmtCr, fmtNum, fmtPct } from "../lib/format";
import type { Meta, ProjectSummary } from "../lib/types";

const COLS: { key: keyof ProjectSummary; label: string; num?: boolean }[] = [
  { key: "project_name", label: "Project" },
  { key: "rag", label: "Status" },
  { key: "trajectory", label: "Trajectory" },
  { key: "risk_composite", label: "Risk", num: true },
  { key: "progress", label: "Progress", num: true },
  { key: "cost_growth_pct", label: "Cost growth", num: true },
  { key: "slip_months", label: "Slip (mo)", num: true },
  { key: "revised_cost_cr", label: "Revised cost", num: true },
  { key: "data_confidence", label: "Data conf.", num: true },
  { key: "priority_index", label: "Priority", num: true },
];

export default function ProjectsPage() {
  const [f, setF] = useState({ q: "", ministry: "", sector: "", rag: "", trajectory: "", status: "Ongoing" });
  const [sort, setSort] = useState<{ key: string; order: "asc" | "desc" }>({ key: "priority_index", order: "desc" });
  const [page, setPage] = useState(0);
  const meta = useApi<Meta>("/meta");
  const size = 50;
  const { data, isLoading, error } = useApi<{ total: number; items: ProjectSummary[] }>(
    `/projects${qs({ ...f, sort: sort.key, order: sort.order, limit: size, offset: page * size })}`);
  const navigate = useNavigate();
  const set = (k: string) => (v: string) => { setF({ ...f, [k]: v }); setPage(0); };

  return (
    <>
      <PageHeader title="Projects" subtitle="Every monitored project with its current risk, trajectory and data confidence." />
      <Card bodyClass="p-0" title={data ? `${data.total} projects` : "Projects"}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search className="absolute left-2 top-2 h-4 w-4 text-slate-400" />
              <input className="input pl-7" placeholder="Search name or ID" value={f.q} onChange={(e) => set("q")(e.target.value)} />
            </div>
            <Select value={f.ministry} onChange={set("ministry")} options={meta.data?.ministries ?? []} placeholder="All ministries" />
            <Select value={f.sector} onChange={set("sector")} options={meta.data?.sectors ?? []} placeholder="All sectors" />
            <Select value={f.rag} onChange={set("rag")} options={["Red", "Amber", "Green"]} placeholder="Any RAG" />
            <Select value={f.trajectory} onChange={set("trajectory")} options={["Rapidly Deteriorating", "Deteriorating", "Stable", "Improving"]} placeholder="Any trajectory" />
            <Select value={f.status} onChange={set("status")} options={["Ongoing", "Completed", "Dropped"]} placeholder="Any status" />
            <ExportButton onClick={async () => {
              const all = await api<{ items: ProjectSummary[] }>(`/projects${qs({ ...f, status: f.status || "all", sort: sort.key, order: sort.order, limit: 1000 })}`);
              downloadCsv("prism_projects.csv", all.items as unknown as Record<string, unknown>[]);
            }} />
          </div>
        }>
        {isLoading ? <Loading /> : error ? <div className="p-4"><ErrorBox error={error} /></div> : (
          <>
            <div className="max-h-[68vh] overflow-auto">
              <table className="tbl">
                <thead>
                  <tr>
                    {COLS.map((c) => (
                      <th key={c.key} className={`cursor-pointer select-none ${c.num ? "text-right" : ""}`}
                        onClick={() => setSort({ key: c.key, order: sort.key === c.key && sort.order === "desc" ? "asc" : "desc" })}>
                        {c.label}
                        {sort.key === c.key && (sort.order === "desc" ? <ArrowDown className="ml-1 inline h-3 w-3" /> : <ArrowUp className="ml-1 inline h-3 w-3" />)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data?.items.map((p) => (
                    <tr key={p.project_id} className="cursor-pointer" onClick={() => navigate(`/projects/${p.project_id}`)}>
                      <td className="max-w-md"><div className="line-clamp-2 font-medium text-slate-900" title={p.project_name}>{p.project_name}</div><div className="muted">{p.project_id} · {p.ministry} · {p.state}</div></td>
                      <td><RagBadge rag={p.rag} /></td>
                      <td><TrajBadge t={p.trajectory} /></td>
                      <td className="text-right tabular-nums">{fmtNum(p.risk_composite)}</td>
                      <td className="w-28 text-right tabular-nums">{fmtPct(p.progress, 0)}<Bar value={p.progress} /></td>
                      <td className="text-right tabular-nums">{fmtPct(p.cost_growth_pct)}</td>
                      <td className="text-right tabular-nums">{fmtNum(p.slip_months, 0)}</td>
                      <td className="text-right tabular-nums">{fmtCr(p.revised_cost_cr)}</td>
                      <td className="text-right tabular-nums">{fmtNum(p.data_confidence, 0)}</td>
                      <td className="text-right font-semibold tabular-nums">{fmtNum(p.priority_index)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex items-center justify-between border-t border-slate-100 px-4 py-2 text-sm">
              <span className="muted">Page {page + 1} of {Math.max(1, Math.ceil((data?.total ?? 0) / size))}</span>
              <div className="flex gap-2">
                <button className="btn-ghost" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
                <button className="btn-ghost" disabled={(page + 1) * size >= (data?.total ?? 0)} onClick={() => setPage(page + 1)}>Next</button>
              </div>
            </div>
          </>
        )}
      </Card>
    </>
  );
}
