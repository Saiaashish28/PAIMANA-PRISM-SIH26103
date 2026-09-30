import { useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { CheckCircle2, Circle, Copy, Download, FlaskConical, Loader2, RefreshCw, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { api, useApi } from "../lib/api";
import type { LlmStatus } from "../lib/types";
import { Card } from "./ui";

type Os = "windows" | "mac" | "linux";
const INSTALL: Record<Os, string[]> = {
  windows: ["# 1. Install: download and run the installer from https://ollama.com/download/windows",
    "#    (Ollama then runs in the system tray)", "# 2. Download the model (~2 GB, once):", "ollama pull qwen2.5:3b"],
  mac: ["# 1. Install: download from https://ollama.com/download/mac (or: brew install ollama)",
    "# 2. Download the model (~2 GB, once):", "ollama pull qwen2.5:3b"],
  linux: ["curl -fsSL https://ollama.com/install.sh | sh", "ollama serve &", "ollama pull qwen2.5:3b"],
};

function Step({ done, active, children }: { done: boolean; active: boolean; children: React.ReactNode }) {
  return (
    <li className={clsx("flex gap-2", !done && !active && "text-slate-400")}>
      {done ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-green-600" />
        : active ? <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" /> : <Circle className="mt-0.5 h-4 w-4 shrink-0" />}
      <div>{children}</div>
    </li>
  );
}

export function LlmSetup() {
  const qc = useQueryClient();
  const [refresh, setRefresh] = useState(0);
  const pulling = (s?: LlmStatus) => s?.job?.state === "pulling" || s?.job?.state === "warming";
  const { data: st, isFetching } = useApi<LlmStatus>(`/llm/status?refresh=${refresh ? 1 : 0}&n=${refresh}`);
  const [os, setOs] = useState<Os>(() => (navigator.userAgent.includes("Windows") ? "windows" : navigator.userAgent.includes("Mac") ? "mac" : "linux"));
  const [msg, setMsg] = useState<string | null>(null);
  const [test, setTest] = useState<{ engine: string; latency_ms: number } | null>(null);
  const [testing, setTesting] = useState(false);

  // while a download runs, poll every 2 s
  useEffect(() => {
    if (!pulling(st)) return;
    const t = window.setTimeout(() => setRefresh((n) => n + 1), 2000);
    return () => window.clearTimeout(t);
  }, [st]);
  useEffect(() => { if (st?.job?.state === "done") qc.invalidateQueries(); }, [st?.job?.state, qc]);

  const recheck = () => { setMsg(null); setRefresh((n) => n + 1); };
  const pull = async () => {
    setMsg(null);
    try { await api("/llm/pull", { method: "POST" }); recheck(); } catch (e) { setMsg((e as Error).message); }
  };
  const runTest = async () => {
    setTesting(true); setTest(null); setMsg(null);
    try { setTest(await api("/llm/test", { method: "POST" })); } catch (e) { setMsg((e as Error).message); } finally { setTesting(false); }
  };

  const step = st?.step ?? "not_running";
  const running = step === "ready" || step === "model_missing";
  const model = st?.model ?? "qwen2.5:3b";
  return (
    <Card title={<span id="llm">Local LLM (Ollama)</span>}
      subtitle="Optional. Without it the assistant composes answers straight from the evidence; with it, Qwen 2.5 3B writes fluent answers that are still number-checked."
      actions={<span className={clsx("chip", step === "ready" ? "bg-green-100 text-green-700" : "bg-slate-100 text-slate-600")}>{step === "ready" ? "On" : "Off"}</span>}>
      <ol className="space-y-2 text-sm">
        <Step done={running} active={!running}>Ollama installed and running <span className="muted">({st?.host ?? "http://127.0.0.1:11434"})</span></Step>
        <Step done={step === "ready"} active={step === "model_missing"}>
          Model <code>{model}</code> downloaded
          {step === "model_missing" && st?.installed_models?.length ? <div className="muted">Installed now: {st.installed_models.join(", ")}</div> : null}
        </Step>
        <Step done={step === "ready"} active={false}>Assistant uses the LLM</Step>
      </ol>
      {st?.hint && <p className={clsx("mt-3 rounded-lg p-2.5 text-xs", step === "ready" ? "bg-green-50 text-green-800" : "bg-amber-50 text-amber-800")}>{st.hint}</p>}

      {pulling(st) && (
        <div className="mt-3">
          <div className="muted mb-1">{st?.job?.status}{st?.job?.percent != null ? ` · ${st.job.percent}%` : ""}</div>
          <div className="h-2 overflow-hidden rounded bg-slate-100"><div className="h-full bg-brand-600 transition-all" style={{ width: `${st?.job?.percent ?? 5}%` }} /></div>
        </div>
      )}
      {st?.job?.state === "failed" && <p className="mt-2 text-xs text-red-600">Download failed: {st.job.error}</p>}

      <div className="mt-3 flex flex-wrap gap-2">
        <button className="btn-ghost text-xs" onClick={recheck} disabled={isFetching}><RefreshCw className={clsx("h-3.5 w-3.5", isFetching && "animate-spin")} /> Check again</button>
        {step === "model_missing" && <button className="btn text-xs" onClick={pull} disabled={pulling(st)}><Download className="h-3.5 w-3.5" /> Download model</button>}
        {step === "ready" && <button className="btn text-xs" onClick={runTest} disabled={testing}>
          {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FlaskConical className="h-3.5 w-3.5" />} Test LLM</button>}
      </div>
      {testing && <p className="muted mt-2">Asking the LLM for a portfolio summary… the first answer can take a minute on a CPU.</p>}
      {test && <p className={clsx("mt-2 text-xs", test.engine.startsWith("ollama") ? "text-green-700" : "text-amber-700")}>
        {test.engine.startsWith("ollama") ? `✓ The LLM answered in ${(test.latency_ms / 1000).toFixed(1)} s.` : `The answer came from the fallback (${test.engine}).`}</p>}
      {msg && <p className="mt-2 text-xs text-red-600">{msg}</p>}

      {step !== "ready" && step !== "disabled" && (
        <div className="mt-4">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-600">Setup commands</span>
            <div className="flex gap-1">{(["windows", "mac", "linux"] as Os[]).map((o) => (
              <button key={o} onClick={() => setOs(o)} className={clsx("rounded px-2 py-0.5 text-[11px]", os === o ? "bg-brand-700 text-white" : "bg-slate-100 text-slate-600")}>
                {o === "windows" ? "Windows" : o === "mac" ? "macOS" : "Linux"}</button>))}</div>
          </div>
          <div className="relative">
            <pre className="overflow-x-auto rounded-lg bg-slate-900 p-2.5 text-[11px] leading-relaxed text-slate-100">{INSTALL[os].join("\n")}</pre>
            <button className="absolute right-1.5 top-1.5 rounded bg-white/10 p-1 text-slate-200 hover:bg-white/20" title="Copy"
              onClick={() => navigator.clipboard?.writeText(INSTALL[os].filter((l) => !l.startsWith("#")).join("\n"))}><Copy className="h-3.5 w-3.5" /></button>
          </div>
          <p className="muted mt-1.5">Then click <b>Check again</b>; no restart of PRISM is needed.</p>
        </div>
      )}
    </Card>
  );
}
