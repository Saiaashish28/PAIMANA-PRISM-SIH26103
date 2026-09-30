import { Search, ShieldCheck, X } from "lucide-react";
import { useState } from "react";
import { ChatPanel } from "../components/ChatPanel";
import { LlmSetup } from "../components/LlmSetup";
import { Card, PageHeader, RagBadge } from "../components/ui";
import { qs, useApi } from "../lib/api";
import type { Meta, ProjectSummary } from "../lib/types";

const PORTFOLIO_QS = [
  "What changed in the latest report?", "Which projects need attention first?", "Give me a portfolio summary",
  "Which sector is riskiest?", "How many projects have 3-month warnings?", "What issues keep recurring?",
  "What is the status of Polavaram?",
];
const PROJECT_QS = [
  "Why is this project at risk?", "What should be done about it?", "When will it finish?",
  "How does it compare with similar projects?", "What changed recently?",
];

export default function AssistantPage() {
  const meta = useApi<Meta>("/meta");
  const llm = meta.data?.llm;
  const [scope, setScope] = useState<ProjectSummary | null>(null);
  const [q, setQ] = useState("");
  const hits = useApi<{ total: number; items: ProjectSummary[] }>(
    q.trim().length >= 2 ? `/projects${qs({ q, status: "all", limit: 8 })}` : null);

  return (
    <>
      <PageHeader title="PRISM assistant"
        subtitle="Ask questions in plain English. Every answer is built from PRISM's own figures and cites them, so nothing is made up." />
      <div className="grid gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <Card title="Scope" subtitle="Ask about the whole portfolio, or pick one project for a detailed answer. Naming a project in the question (e.g. “Polavaram” or “PM-612068”) also works.">
            {scope ? (
              <div className="flex flex-wrap items-center gap-2 rounded-lg bg-brand-50 px-3 py-2 text-sm">
                <span className="font-medium text-slate-800">{scope.project_name}</span>
                <span className="muted">{scope.project_id}</span>
                <RagBadge rag={scope.rag} />
                <button className="btn-ghost ml-auto text-xs" onClick={() => setScope(null)}><X className="h-3.5 w-3.5" /> Back to portfolio</button>
              </div>
            ) : (
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
                <input className="input w-full pl-8" placeholder="Whole portfolio — or type a project name / ID to focus on one project…"
                  value={q} onChange={(e) => setQ(e.target.value)} />
                {q.trim().length >= 2 && (
                  <ul className="absolute z-10 mt-1 max-h-72 w-full overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-lg">
                    {hits.data?.items.length === 0 && <li className="muted px-3 py-2">No matching project.</li>}
                    {hits.data?.items.map((p) => (
                      <li key={p.project_id}>
                        <button className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-slate-50"
                          onClick={() => { setScope(p); setQ(""); }}>
                          <span className="line-clamp-1 flex-1">{p.project_name}</span>
                          <span className="muted">{p.project_id}</span>
                          <RagBadge rag={p.rag} />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </Card>
          <Card title={scope ? `Conversation — ${scope.project_id}` : "Conversation — whole portfolio"}>
            <ChatPanel key={scope?.project_id ?? "portfolio"} height={560} projectId={scope?.project_id}
              suggestions={scope ? PROJECT_QS : PORTFOLIO_QS} />
          </Card>
        </div>
        <div className="space-y-4">
          <LlmSetup />
          <Card title="How to use it">
            <ol className="list-decimal space-y-2 pl-4 text-sm text-slate-700">
              <li>Click one of the example questions, or type your own and press <b>Ask</b>.</li>
              <li>For one project, pick it in <b>Scope</b>, or open a project page and use its assistant tab. You can also just name it in the question.</li>
              <li>Numbers in brackets like <sup className="rounded bg-brand-100 px-1 text-[10px] font-semibold text-brand-700">E3</sup> are citations. Open <b>Evidence used</b> under an answer to see the exact figure.</li>
              <li>Follow-up questions keep the conversation context.</li>
            </ol>
            <div className="mt-3 text-xs text-slate-500">Good questions: what changed, why a project is at risk, what to do, when it will finish, which ministries/sectors are worst, which issues recur.</div>
          </Card>
          <Card title="How answers are produced">
            <ol className="list-decimal space-y-2 pl-4 text-sm text-slate-700">
              <li><b>Evidence Packager</b> collects citable facts (E1…En): risk scores, drivers, report changes, forecasts, similar projects.</li>
              <li><b>Local LLM</b> ({llm?.model ?? "Qwen 2.5 3B"} via Ollama) writes the answer using only that evidence.</li>
              <li><b>Grounding Validator</b> checks every number and citation. If a check fails, the LLM gets one retry before PRISM falls back to an answer composed from the evidence.</li>
            </ol>
            <div className="mt-3 flex items-center gap-2 text-sm text-slate-700"><ShieldCheck className="h-4 w-4 text-brand-700" /> Everything runs locally; project data never leaves this machine.</div>
          </Card>
        </div>
      </div>
    </>
  );
}
