import clsx from "clsx";
import { Bot, CheckCircle2, Send, ShieldAlert, Sparkles, User } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, useApi } from "../lib/api";
import type { AskResponse, LlmStatus } from "../lib/types";

type Turn = { role: "user" | "assistant"; content: string; res?: AskResponse };

/** Renders an answer with [E#] citations as small badges. */
function Cited({ text }: { text: string }) {
  const parts = text.split(/(\[E\d+\])/g);
  return (
    <>
      {parts.map((p, i) =>
        /^\[E\d+\]$/.test(p)
          ? <sup key={i} className="mx-0.5 rounded bg-brand-100 px-1 text-[10px] font-semibold text-brand-700">{p.slice(1, -1)}</sup>
          : <span key={i}>{p}</span>)}
    </>
  );
}

export function ChatPanel({ projectId, suggestions, height = 460 }: { projectId?: string; suggestions: string[]; height?: number }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const llmOn = useApi<LlmStatus>("/llm/status").data?.available ?? false;
  // block body: newer Chrome returns a Promise from scrollIntoView, which React would treat as a cleanup
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, [turns]);

  const ask = async (question: string) => {
    if (!question.trim() || busy) return;
    setBusy(true);
    setErr(null);
    const history = turns.map(({ role, content }) => ({ role, content }));
    setTurns((t) => [...t, { role: "user", content: question }]);
    setQ("");
    try {
      const res = await api<AskResponse>("/assistant/ask", {
        method: "POST", body: JSON.stringify({ question, project_id: projectId ?? null, history }),
      });
      setTurns((t) => [...t, { role: "assistant", content: res.answer, res }]);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col" style={{ height }}>
      <div className="flex-1 space-y-3 overflow-y-auto pr-1">
        {turns.length === 0 && (
          <div className="space-y-2">
            <p className="muted">Answers are composed only from this {projectId ? "project's" : "portfolio's"} evidence package; every number is checked by the grounding validator.</p>
            <div className="flex flex-wrap gap-2">
              {suggestions.map((s) => <button key={s} className="btn-ghost text-xs" onClick={() => ask(s)}>{s}</button>)}
            </div>
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} className={clsx("flex gap-2", t.role === "user" && "justify-end")}>
            {t.role === "assistant" && <Bot className="mt-1 h-5 w-5 shrink-0 text-brand-700" />}
            <div className={clsx("max-w-[88%] rounded-xl px-3 py-2 text-sm leading-relaxed",
              t.role === "user" ? "bg-brand-700 text-white" : "border border-slate-200 bg-slate-50 text-slate-800")}>
              <div className="whitespace-pre-wrap">{t.role === "assistant" ? <Cited text={t.content} /> : t.content}</div>
              {t.res && (
                <div className="mt-2 space-y-1 border-t border-slate-200 pt-2 text-[11px] text-slate-500">
                  <div className="flex flex-wrap items-center gap-2">
                    {t.res.grounding.grounded
                      ? <span className="chip bg-green-100 text-green-700"><CheckCircle2 className="mr-1 h-3 w-3" />Grounded · {t.res.grounding.numbers_checked} numbers verified</span>
                      : <span className="chip bg-red-100 text-red-700"><ShieldAlert className="mr-1 h-3 w-3" />Grounding failed</span>}
                    {t.res.scope === "project" && t.res.project_id && !projectId &&
                      <Link to={`/projects/${t.res.project_id}`} className="chip bg-brand-100 text-brand-700">about {t.res.project_id}</Link>}
                    {t.res.engine.startsWith("ollama")
                      ? <span className="chip bg-violet-100 text-violet-700"><Sparkles className="mr-1 h-3 w-3" />Written by {t.res.engine.slice(7)} (Ollama)</span>
                      : <span className="chip bg-slate-100 text-slate-600" title={t.res.engine}>Composed from evidence{t.res.engine.includes("rejected") ? " (LLM answer failed validation)" : t.res.llm?.available ? "" : " · LLM off"}</span>}
                    <span>{t.res.latency_ms} ms</span>
                  </div>
                  {t.res.evidence_used.length > 0 && (
                    <details>
                      <summary className="cursor-pointer">Evidence used ({t.res.evidence_used.length})</summary>
                      <ul className="mt-1 space-y-1">
                        {t.res.evidence_used.map((e) => <li key={e.id}><b className="text-brand-700">{e.id}</b> {e.text}</li>)}
                      </ul>
                    </details>
                  )}
                </div>
              )}
            </div>
            {t.role === "user" && <User className="mt-1 h-5 w-5 shrink-0 text-slate-400" />}
          </div>
        ))}
        {busy && <div className="muted flex items-center gap-2"><Bot className="h-4 w-4 animate-pulse" />
          {llmOn ? "Writing the answer with the local LLM… (the first answer can take a minute on a CPU)" : "Assembling evidence…"}</div>}
        {err && <div className="text-sm text-red-600">{err}</div>}
        <div ref={end} />
      </div>
      <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); ask(q); }}>
        <input className="input flex-1" placeholder={projectId ? "Ask about this project…" : "Ask about the portfolio…"} value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="btn" disabled={busy || !q.trim()}><Send className="h-4 w-4" /> Ask</button>
      </form>
    </div>
  );
}
