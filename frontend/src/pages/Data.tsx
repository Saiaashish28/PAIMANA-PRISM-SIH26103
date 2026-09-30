import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, FileSpreadsheet, FileText, FolderOpen, Loader2, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { Card, PageHeader } from "../components/ui";
import { ApiError, useApi } from "../lib/api";
import { fmtMonth } from "../lib/format";

interface DataStatus {
  active_source: "real" | "synthetic" | null;
  configured_source: string;
  real_folder: string;
  real_files: { name: string; size_kb: number }[];
  building: boolean;
  last_error: string | null;
  loaded: { data_dir: string; files: string[]; ingest_notes: string[]; first_month: string; n_projects: number } | null;
  as_of: string | null;
  importing: boolean;
  import_results: { file: string; status: string; month?: string; rows?: number; detail?: string }[];
  report_pdfs: string[];
}
interface UploadResult { saved: string[]; projects: number; monthly_rows: number; months: number; notes: string[]; detail: string }

export default function DataPage() {
  const qc = useQueryClient();
  const { data: st } = useApi<DataStatus>("/data/status", { refetchInterval: 3000 });
  const input = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const upload = async () => {
    setBusy(true); setErr(null); setResult(null);
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    try {
      const res = await fetch("/api/data/upload", { method: "POST", body: fd });
      const body = await res.json();
      if (!res.ok) throw new ApiError(res.status, typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail));
      setResult(body);
      setFiles([]);
      qc.invalidateQueries();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const real = st?.active_source === "real";
  const runImport = async () => {
    setErr(null);
    await fetch("/api/data/import-reports", { method: "POST" });
    qc.invalidateQueries({ queryKey: ["/data/status"] });
  };
  const imported = (st?.import_results ?? []).filter((r) => r.status === "imported" || r.status === "cached");
  const skipped = (st?.import_results ?? []).filter((r) => !["imported", "cached"].includes(r.status));
  return (
    <>
      <PageHeader title="Data sources" subtitle="Load real PAIMANA / OCMS exports. PRISM validates them, then retrains every model on them." />

      <div className={`mb-4 flex items-start gap-3 rounded-xl border p-4 ${real ? "border-green-200 bg-green-50" : "border-amber-200 bg-amber-50"}`}>
        {real ? <CheckCircle2 className="mt-0.5 h-5 w-5 text-green-600" /> : <AlertTriangle className="mt-0.5 h-5 w-5 text-amber-600" />}
        <div className="text-sm">
          <div className="font-semibold">{real ? "Running on real data" : "Running on synthetic demo data"}</div>
          <div className="text-slate-600">
            {st?.loaded ? `${st.loaded.n_projects} projects · ${fmtMonth(st.loaded.first_month)} to ${fmtMonth(st.as_of)} · ${st.loaded.data_dir}` : "…"}
          </div>
          {!real && <div className="mt-1 text-slate-600">All scores and results are from simulated projects until real files are added below.</div>}
        </div>
        {st?.building && <span className="ml-auto flex items-center gap-1.5 text-sm text-brand-700"><Loader2 className="h-4 w-4 animate-spin" /> Retraining…</span>}
      </div>

      {st?.last_error && (
        <div className="mb-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          <div className="font-semibold">Last retraining failed. The app is still showing the previous data.</div>
          <div className="mt-1">{st.last_error}</div>
        </div>
      )}

      <Card className="mb-4" title={<span className="flex items-center gap-1.5"><FileText className="h-4 w-4" /> Flash Report PDFs</span>}
        subtitle={`${st?.report_pdfs.length ?? 0} PDF(s) in data/reports/. Monthly Flash Reports (2024 onwards) are converted into one table per month in data/real/.`}
        actions={<button className="btn" disabled={st?.importing || st?.building || !st?.report_pdfs.length} onClick={runImport}>
          {st?.importing ? <><Loader2 className="h-4 w-4 animate-spin" /> Extracting…</> : "Import PDFs & retrain"}</button>}>
        {st?.importing && <p className="muted mb-2">Reading every table in every report — this takes several minutes for a full archive.</p>}
        {(st?.import_results.length ?? 0) > 0 ? (
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <div className="card-title mb-1">Imported ({imported.length})</div>
              <ul className="max-h-56 space-y-0.5 overflow-y-auto text-xs">
                {imported.sort((a, b) => (a.month ?? "").localeCompare(b.month ?? "")).map((r) => (
                  <li key={r.file} className="flex justify-between gap-2"><span className="truncate">{r.file.split("/").pop()}</span>
                    <span className="shrink-0 text-slate-500">{r.month}{r.rows ? ` · ${r.rows} projects` : ""}</span></li>))}
              </ul>
            </div>
            <div>
              <div className="card-title mb-1">Not imported ({skipped.length})</div>
              <ul className="max-h-56 space-y-0.5 overflow-y-auto text-xs">
                {skipped.map((r) => (
                  <li key={r.file}><span className="font-medium">{r.file.split("/").pop()}</span> <span className="text-slate-500">— {r.status}{r.detail ? `: ${r.detail}` : ""}</span></li>))}
              </ul>
            </div>
          </div>
        ) : <p className="muted">Not imported yet in this session. Existing extracts in data/real/ are used automatically.</p>}
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Upload files" subtitle="CSV or Excel. Either one file per reporting month (e.g. PAIMANA_April_2025.xlsx) or project_master + monthly_snapshots">
          <div onClick={() => input.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); setFiles([...files, ...Array.from(e.dataTransfer.files)]); }}
            className="flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed border-slate-300 p-8 text-center hover:border-brand-600 hover:bg-brand-50">
            <Upload className="h-8 w-8 text-slate-400" />
            <div className="text-sm font-medium text-slate-700">Drop files here or click to choose</div>
            <div className="muted">.csv · .xlsx · .xls — several files at once is fine</div>
            <input ref={input} type="file" multiple accept=".csv,.xlsx,.xls" className="hidden"
              onChange={(e) => setFiles([...files, ...Array.from(e.target.files ?? [])])} />
          </div>
          {files.length > 0 && (
            <div className="mt-3 space-y-2">
              <ul className="max-h-40 space-y-1 overflow-y-auto text-sm">
                {files.map((f, i) => <li key={i} className="flex items-center gap-2"><FileSpreadsheet className="h-4 w-4 text-green-700" />{f.name}<span className="muted">{(f.size / 1024).toFixed(0)} KB</span></li>)}
              </ul>
              <div className="flex gap-2">
                <button className="btn" disabled={busy} onClick={upload}>{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />} Validate & load {files.length} file(s)</button>
                <button className="btn-ghost" disabled={busy} onClick={() => setFiles([])}>Clear</button>
              </div>
            </div>
          )}
          {err && <div className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-700"><b>Not accepted.</b> {err}</div>}
          {result && (
            <div className="mt-3 rounded-lg bg-green-50 p-3 text-sm text-green-800">
              <b>Accepted:</b> {result.projects} projects, {result.months} months, {result.monthly_rows} project-month rows. {result.detail}
              {result.notes.length > 0 && <ul className="mt-1 list-disc pl-5 text-xs text-green-900">{result.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
            </div>
          )}
        </Card>

        <Card title={<span className="flex items-center gap-1.5"><FolderOpen className="h-4 w-4" /> Files in the real-data folder</span>} subtitle={st?.real_folder}>
          {st?.real_files.length ? (
            <ul className="max-h-64 space-y-1 overflow-y-auto text-sm">
              {st.real_files.map((f) => <li key={f.name} className="flex justify-between"><span>{f.name}</span><span className="muted">{f.size_kb} KB</span></li>)}
            </ul>
          ) : <p className="muted">Empty. You can also copy files straight into <code>data/real/</code> and restart the API.</p>}
          {st?.loaded?.ingest_notes && st.loaded.ingest_notes.length > 0 && (
            <div className="mt-4 border-t border-slate-100 pt-3">
              <div className="card-title mb-1">What PRISM adjusted when reading the current data</div>
              <ul className="list-disc space-y-0.5 pl-5 text-xs text-slate-600">{st.loaded.ingest_notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
            </div>
          )}
        </Card>
      </div>

      <Card className="mt-4" title="What the files need">
        <div className="grid gap-4 text-sm text-slate-700 md:grid-cols-2">
          <div>
            <div className="font-medium">Project details</div>
            <p className="muted mb-1">In a project_master file, or as extra columns in the monthly files</p>
            <p>Project ID, Project Name, Ministry, Sector, State, Date of Start, Original Date of Completion, Original Cost (Rs Cr)</p>
          </div>
          <div>
            <div className="font-medium">Every month</div>
            <p className="muted mb-1">Month can come from a column or the file name</p>
            <p>Project ID, Month, Physical Progress (%), Cumulative Expenditure (Rs Cr), Anticipated/Revised Cost (Rs Cr), Anticipated Date of Completion, Remarks (optional)</p>
          </div>
        </div>
        <p className="muted mt-3">Column names are matched flexibly. Models need history: aim for 24+ consecutive months. Full guide: <code>data/real/README.md</code>.</p>
      </Card>
    </>
  );
}
