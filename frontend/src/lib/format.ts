export const RAG_COLOR: Record<string, string> = {
  Red: "#dc2626",
  Amber: "#f59e0b",
  Green: "#16a34a",
  Completed: "#64748b",
  Dropped: "#a8a29e",
};

export const TRAJ_COLOR: Record<string, string> = {
  "Rapidly Deteriorating": "#b91c1c",
  Deteriorating: "#f97316",
  Stable: "#64748b",
  Improving: "#16a34a",
};

export const DIM_COLOR: Record<string, string> = {
  cost: "#7c3aed",
  schedule: "#2563eb",
  implementation: "#0d9488",
};

export const DIM_LABEL: Record<string, string> = {
  cost: "Cost overrun",
  schedule: "Schedule slippage",
  implementation: "Implementation stall",
};

export const fmtNum = (v: number | null | undefined, d = 1) =>
  v === null || v === undefined || Number.isNaN(v) ? "–" : v.toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d });

export const fmtPct = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? "–" : `${fmtNum(v, d)}%`);

export const fmtProb = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${(v * 100).toFixed(0)}%`);

/** Rs crore with lakh-crore shorthand for large totals. */
export const fmtCr = (v: number | null | undefined) => {
  if (v === null || v === undefined) return "–";
  if (Math.abs(v) >= 100_000) return `₹${(v / 100_000).toFixed(2)} L Cr`;
  return `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })} Cr`;
};

export const fmtMonth = (ym: string | null | undefined) => {
  if (!ym) return "–";
  const [y, m] = ym.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleString("en-IN", { month: "short", year: "numeric" });
};

/** "Railways" -> "Ministry of Railways"; names that already say Ministry/Department are kept. */
export const ministryLabel = (m: string) => (/^(ministry|department|dept)\b/i.test(m) ? m : `Ministry of ${m}`);
