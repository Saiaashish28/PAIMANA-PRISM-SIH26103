import clsx from "clsx";
import { CalendarClock, CheckCircle2, FolderSearch, IndianRupee, PlusCircle, Radio } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Card, Empty, ErrorBox, Kpi, Loading, PageHeader, RagBadge, Segmented } from "../components/ui";
import { useApi } from "../lib/api";
import { fmtCr, fmtMonth, fmtNum } from "../lib/format";
import { KIND_LABEL, SEV_STYLE, timeAgo, useLive, type FeedEvent } from "../lib/live";

interface Item { project_id: string; project_name: string; ministry: string; rag: string }
interface Changes {
  month: string; previous_month: string | null;
  summary: { reported: number; cost_revisions: number; cost_added_cr: number; schedule_slips: number; months_added: number; completed: number; new: number; left_list: number; no_progress: number };
  cost_revisions: (Item & { from_cr: number; to_cr: number; added_cr: number })[];
  schedule_slips: (Item & { from: string; to: string; months: number })[];
  completed: Item[];
  new: (Item & { original_cost_cr: number | null })[];
  watching: { enabled: boolean; interval_s: number; folders: string[]; files: number | null; last_check: string | null; listeners: number };
}

type Filter = "all" | FeedEvent["kind"];

export default function LiveFeedPage() {
  const { events, status, lastUpdate } = useLive();
  const history = useApi<FeedEvent[]>("/events?limit=300");
  const { data: ch, isLoading, error } = useApi<Changes>("/changes/latest", { refetchInterval: 30_000 });
  const [filter, setFilter] = useState<Filter>("all");
  const [tab, setTab] = useState<"slips" | "cost" | "done" | "new">("slips");

  // stream events (newest) + persisted history, de-duplicated by id
  const all = useMemo(() => {
    const seen = new Set<number>();
    return [...events, ...(history.data ?? [])].filter((e) => {
      if (e.id === null) return true;
      if (seen.has(e.id)) return false;
      seen.add(e.id);
      return true;
    });
  }, [events, history.data]);
  const shown = all.filter((e) => filter === "all" || e.kind === filter);

  return (
    <>
      <PageHeader title="Live feed"
        subtitle="What changed in the latest PAIMANA report, and everything PRISM detects as it happens. New reports dropped into data/reports/ are picked up automatically."
        actions={
          <div className={clsx("flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs",
            status === "live" ? "border-green-200 bg-green-50 text-green-700" : "border-slate-200 bg-slate-50 text-slate-500")}>
            <Radio className={clsx("h-4 w-4", status === "live" && "live-dot")} />
            {status === "live" ? "Connected — updates appear instantly" : "Reconnecting to the live stream…"}
            {lastUpdate && <span className="text-slate-500">· data refreshed {lastUpdate.toLocaleTimeString()}</span>}
          </div>
        } />

      {isLoading ? <Loading /> : error || !ch ? <ErrorBox error={error} /> : (
        <>
          <div className="mb-2 text-sm font-semibold text-slate-700">
            {fmtMonth(ch.month)} report{ch.previous_month ? ` vs ${fmtMonth(ch.previous_month)}` : ""} · {fmtNum(ch.summary.reported, 0)} projects reported
          </div>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Kpi label="Schedule slips" tone="red" value={fmtNum(ch.summary.schedule_slips, 0)} hint={`+${fmtNum(ch.summary.months_added, 0)} months of delay added`} icon={<CalendarClock className="h-4 w-4" />} />
            <Kpi label="Cost revisions" tone="amber" value={fmtNum(ch.summary.cost_revisions, 0)} hint={`+${fmtCr(ch.summary.cost_added_cr)}`} icon={<IndianRupee className="h-4 w-4" />} />
            <Kpi label="Completed" tone="green" value={fmtNum(ch.summary.completed, 0)} hint={`${ch.summary.left_list} left the list since last report`} icon={<CheckCircle2 className="h-4 w-4" />} />
            <Kpi label="Newly added" tone="blue" value={fmtNum(ch.summary.new, 0)} hint={`${fmtNum(ch.summary.no_progress, 0)} reported no progress this month`} icon={<PlusCircle className="h-4 w-4" />} />
          </div>

          <div className="mt-4 grid gap-4 xl:grid-cols-5">
            <Card className="xl:col-span-3" title="Changes in the latest report" bodyClass="p-0"
              actions={<Segmented value={tab} onChange={setTab} options={[
                { key: "slips", label: `Slips (${ch.summary.schedule_slips})` }, { key: "cost", label: `Cost (${ch.summary.cost_revisions})` },
                { key: "done", label: `Completed (${ch.summary.completed})` }, { key: "new", label: `New (${ch.summary.new})` }]} />}>
              <div className="max-h-[32rem] overflow-y-auto">
                <div className="muted px-4 pt-2">Largest {ch.schedule_slips.length >= 40 || ch.completed.length >= 40 ? "40 " : ""}changes, highest-priority projects first.</div>
                <table className="tbl">
                  <tbody>
                    {tab === "slips" && ch.schedule_slips.map((r) => (
                      <Row key={r.project_id} r={r} right={<><b className="text-red-600">+{r.months} mo</b><div className="muted">{fmtMonth(r.from)} → {fmtMonth(r.to)}</div></>} />))}
                    {tab === "cost" && ch.cost_revisions.map((r) => (
                      <Row key={r.project_id} r={r} right={<><b className="text-amber-600">+{fmtCr(r.added_cr)}</b><div className="muted">{fmtCr(r.from_cr)} → {fmtCr(r.to_cr)}</div></>} />))}
                    {tab === "done" && ch.completed.map((r) => <Row key={r.project_id} r={r} right={<span className="chip bg-green-100 text-green-700">Completed</span>} />)}
                    {tab === "new" && ch.new.map((r) => <Row key={r.project_id} r={r} right={<span className="text-sm">{fmtCr(r.original_cost_cr)}</span>} />)}
                  </tbody>
                </table>
                {((tab === "slips" && !ch.schedule_slips.length) || (tab === "cost" && !ch.cost_revisions.length) ||
                  (tab === "done" && !ch.completed.length) || (tab === "new" && !ch.new.length)) &&
                  <div className="p-4"><Empty>Nothing of this kind in the {fmtMonth(ch.month)} report{tab === "cost" ? " (this edition may not report revised costs)" : ""}.</Empty></div>}
              </div>
            </Card>

            <Card className="xl:col-span-2" title="Activity" bodyClass="p-0"
              actions={<select className="input text-xs" value={filter} onChange={(e) => setFilter(e.target.value as Filter)}>
                <option value="all">All events</option>
                {(Object.keys(KIND_LABEL) as FeedEvent["kind"][]).map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
              </select>}>
              <ol className="max-h-[32rem] divide-y divide-slate-100 overflow-y-auto">
                {shown.length === 0 && <li className="p-4"><Empty>No events yet.</Empty></li>}
                {shown.map((e, i) => (
                  <li key={e.id ?? `s${i}`} className="px-4 py-3">
                    <div className="flex items-center gap-2 text-[11px]">
                      <span className={clsx("chip border", SEV_STYLE[e.severity])}>{KIND_LABEL[e.kind]}</span>
                      <span className="text-slate-400" title={new Date(e.ts).toLocaleString()}>{timeAgo(e.ts)}</span>
                      {e.month && <span className="text-slate-400">· {fmtMonth(e.month)}</span>}
                    </div>
                    {e.project_id
                      ? <Link to={`/projects/${e.project_id}`} className="mt-1 block text-sm font-medium text-slate-800 hover:text-brand-700">{e.title}</Link>
                      : <div className="mt-1 text-sm font-medium text-slate-800">{e.title}</div>}
                    {e.detail && <div className="mt-0.5 text-xs text-slate-500">{e.detail}</div>}
                  </li>
                ))}
              </ol>
            </Card>
          </div>

          <Card className="mt-4" title={<span className="flex items-center gap-1.5"><FolderSearch className="h-4 w-4" /> Automatic updates</span>}>
            <div className="grid gap-3 text-sm text-slate-700 md:grid-cols-3">
              <div><div className="muted">Watching</div>{ch.watching.enabled ? `${ch.watching.folders.join(" and ")} every ${ch.watching.interval_s}s` : "disabled (PRISM_WATCH_INTERVAL=0)"}</div>
              <div><div className="muted">Files tracked · last check</div>{ch.watching.files ?? "–"} · {ch.watching.last_check ?? "not yet"}</div>
              <div><div className="muted">How to add a month</div>Put the new Flash Report PDF in <code>data/reports/</code>. PRISM extracts it, retrains and this page updates on its own.</div>
            </div>
          </Card>
        </>
      )}
    </>
  );
}

function Row({ r, right }: { r: Item; right: React.ReactNode }) {
  return (
    <tr>
      <td className="max-w-md">
        <Link to={`/projects/${r.project_id}`} className="line-clamp-2 font-medium text-slate-800 hover:text-brand-700">{r.project_name}</Link>
        <div className="muted">{r.project_id} · {r.ministry}</div>
      </td>
      <td>{r.rag && <RagBadge rag={r.rag} />}</td>
      <td className="whitespace-nowrap text-right">{right}</td>
    </tr>
  );
}
