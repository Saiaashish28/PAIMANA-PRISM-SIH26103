export type Rag = "Red" | "Amber" | "Green" | "Completed" | "Dropped";
export type Dimension = "cost" | "schedule" | "implementation";

export interface Health {
  status: "ready" | "warming_up" | "error";
  detail?: string | null;
  as_of?: string | null;
  build_seconds?: number | null;
  llm?: LlmStatus | null;
  data_source?: "real" | "synthetic" | null;
  building?: boolean;
}

export interface LlmStatus {
  available: boolean;
  model: string;
  host?: string;
  reason?: string | null;
  step?: "ready" | "model_missing" | "not_running" | "disabled";
  hint?: string;
  installed_models?: string[];
  job?: { state: "idle" | "pulling" | "warming" | "done" | "failed"; status: string | null; percent: number | null; error: string | null };
}

export interface Meta {
  as_of: string;
  n_projects: number;
  n_snapshots: number;
  ministries: string[];
  sectors: string[];
  states: string[];
  horizons: number[];
  dimensions: Dimension[];
  dimension_labels: Record<Dimension, string>;
  action_types: Record<string, string>;
  bottleneck_labels: Record<string, string>;
  llm: LlmStatus;
}

export interface ProjectSummary {
  project_id: string;
  project_name: string;
  ministry: string;
  sector: string;
  state: string;
  status: string;
  rag: Rag;
  trajectory: string;
  risk_composite: number;
  risk_cost: number;
  risk_schedule: number;
  risk_implementation: number;
  risk_velocity: number;
  priority_index: number;
  progress: number;
  cost_growth_pct: number;
  slip_months: number;
  original_cost_cr: number;
  revised_cost_cr: number;
  data_confidence: number;
  confidence_grade: string;
  n_warnings: number;
  latitude?: number | null;
  longitude?: number | null;
}

export interface Warning {
  project_id: string;
  project_name?: string;
  ministry?: string;
  sector?: string;
  dimension: Dimension;
  warning: string;
  horizon_months: number;
  severity: "Critical" | "High" | "Watch";
  probability: number | null;
  threshold: number | null;
  trajectory: string;
  risk_velocity: number;
  source: "model" | "anomaly";
  rag?: Rag;
  risk_composite?: number;
  priority_index?: number;
  data_confidence?: number;
}

export interface ProjectDetail extends ProjectSummary {
  implementing_agency: string;
  contractor_name: string;
  start_date: string;
  original_completion: string;
  revised_completion: string;
  report_month: string;
  expenditure: number;
  expenditure_ratio: number;
  expected_progress: number;
  completion_gap: number;
  velocity_3m: number;
  velocity_6m: number;
  required_velocity: number;
  n_cost_revisions: number;
  n_schedule_revisions: number;
  risk_acceleration: number;
  bottleneck: string;
  bottleneck_label: string;
  bottleneck_streak: number;
  staleness_months: number;
  n_contradictions: number;
  n_anomalies: number;
  cost_q10: number | null;
  cost_q50: number | null;
  cost_q90: number | null;
  time_q10: number | null;
  time_q50: number | null;
  time_q90: number | null;
  contractor_credit_score: number;
  land_acquisition_friction_score: number;
  weather_geopolitical_risk_index: number;
  probabilities: Record<Dimension, Record<string, number>>;
  thresholds: Record<Dimension, Record<string, number>>;
  warnings: Warning[];
}

export interface Driver {
  feature: string;
  label: string;
  value: number | null;
  shap: number;
  direction: string;
  non_cuf: boolean;
}

export interface EvidenceItem {
  id: string;
  category: string;
  label: string;
  value: unknown;
  unit: string | null;
  text: string;
}

export interface Pathway {
  action_type: string;
  text: string;
  because: string;
}

export interface AskResponse {
  answer: string;
  engine: string;
  llm: LlmStatus;
  grounding: {
    grounded: boolean;
    numbers_checked: number;
    ungrounded_numbers: number[];
    invalid_citations: string[];
    citations: string[];
    missing_citations: boolean;
  };
  evidence_used: EvidenceItem[];
  latency_ms: number;
  scope: "project" | "portfolio";
  project_id: string | null;
}

export interface Intervention {
  id: number;
  project_id: string;
  project_name?: string;
  ministry?: string;
  intervention_month: string;
  action_type: string;
  description: string;
  authority: string | null;
  source: "historical" | "user";
  risk_before?: number;
  risk_after_3m?: number | null;
  risk_after_6m?: number | null;
  velocity_before?: number;
  velocity_after_6m?: number | null;
  delta_risk?: number | null;
  excess_vs_control?: number | null;
  bottleneck_resolved_6m?: boolean | null;
  outcome: string;
}
