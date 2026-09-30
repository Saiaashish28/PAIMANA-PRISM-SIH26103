import { useMemo, useState } from "react";
import { CircleMarker, MapContainer, Popup, TileLayer } from "react-leaflet";
import { Link } from "react-router-dom";
import { Card, ErrorBox, Loading, PageHeader, RagBadge, Select, TrajBadge } from "../components/ui";
import { useApi } from "../lib/api";
import { RAG_COLOR, fmtCr, fmtNum } from "../lib/format";
import type { Meta } from "../lib/types";

interface Pt {
  project_id: string; project_name: string; ministry: string; sector: string; state: string; status: string; rag: string;
  risk_composite: number; trajectory: string; latitude: number | null; longitude: number | null; revised_cost_cr: number; priority_index: number;
}
interface StateRow { name: string; ongoing: number; avg_risk: number; red: number; cost_escalation_pct: number }

export default function MapPage() {
  const { data, isLoading, error } = useApi<Pt[]>("/map");
  const intel = useApi<{ by_state: StateRow[] }>("/portfolio/intelligence");
  const meta = useApi<Meta>("/meta");
  const [ministry, setMinistry] = useState("");
  const [rag, setRag] = useState("");
  const [showDone, setShowDone] = useState(false);
  const pts = useMemo(() => (data ?? []).filter((p) => p.latitude !== null && (showDone || p.status === "Ongoing")
    && (!ministry || p.ministry === ministry) && (!rag || p.rag === rag)), [data, ministry, rag, showDone]);
  const maxCost = Math.max(...pts.map((p) => p.revised_cost_cr), 1);

  if (isLoading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  return (
    <>
      <PageHeader title="Geographic risk view" subtitle="Project locations coloured by RAG status; marker size scales with revised cost."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Select value={ministry} onChange={setMinistry} options={meta.data?.ministries ?? []} placeholder="All ministries" />
            <Select value={rag} onChange={setRag} options={["Red", "Amber", "Green", "Completed", "Dropped"]} placeholder="Any RAG" />
            <label className="flex items-center gap-1.5 text-sm"><input type="checkbox" checked={showDone} onChange={(e) => setShowDone(e.target.checked)} /> Include completed</label>
          </div>
        } />
      <div className="grid gap-4 xl:grid-cols-4">
        <div className="card overflow-hidden xl:col-span-3" style={{ height: "72vh" }}>
          <MapContainer center={[22.5, 80]} zoom={5} style={{ height: "100%", width: "100%" }} scrollWheelZoom>
            <TileLayer attribution='&copy; OpenStreetMap contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
            {pts.map((p) => (
              <CircleMarker key={p.project_id} center={[p.latitude!, p.longitude!]} radius={4 + 14 * Math.sqrt(p.revised_cost_cr / maxCost)}
                pathOptions={{ color: RAG_COLOR[p.rag], fillColor: RAG_COLOR[p.rag], fillOpacity: 0.55, weight: 1 }}>
                <Popup>
                  <div className="space-y-1 text-sm">
                    <Link to={`/projects/${p.project_id}`} className="font-semibold text-brand-700">{p.project_name}</Link>
                    <div className="text-xs text-slate-500">{p.project_id} · {p.ministry}</div>
                    <div className="flex gap-1"><RagBadge rag={p.rag} /><TrajBadge t={p.trajectory} /></div>
                    <div className="text-xs">Risk {fmtNum(p.risk_composite)} · {fmtCr(p.revised_cost_cr)} · priority {fmtNum(p.priority_index)}</div>
                  </div>
                </Popup>
              </CircleMarker>
            ))}
          </MapContainer>
        </div>
        <Card title="States by average risk" subtitle={`${pts.length} projects shown`} bodyClass="p-0">
          <div className="max-h-[64vh] overflow-y-auto">
            <table className="tbl">
              <thead><tr><th>State</th><th className="text-right">Ongoing</th><th className="text-right">Red</th><th className="text-right">Avg risk</th></tr></thead>
              <tbody>
                {intel.data?.by_state.map((s) => (
                  <tr key={s.name}><td>{s.name}</td><td className="text-right">{s.ongoing}</td><td className="text-right text-red-600">{s.red}</td><td className="text-right tabular-nums">{fmtNum(s.avg_risk)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </>
  );
}
