export const API_BASE_URL: string =
  import.meta.env.VITE_API_URL ?? (import.meta.env.PROD ? "" : "http://127.0.0.1:8000");

export type PipelineStep = { key: string; label: string; detail: string; state: "pending" | "active" | "complete" | "failed" };
export type IngestionJob = {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  progress: number;
  files_received: number;
  files_processed: number;
  steps: PipelineStep[];
  message: string;
  error?: string | null;
  log?: string[];
  failures?: Array<{ file: string; error: string }>;
  summary?: Record<string, unknown> | null;
};

export type Summary = {
  has_data: boolean;
  documents: number;
  source_files: number;
  fields: number;
  transactions: number;
  verified_transactions: number;
  auto_verified_rate: number | null;
  verified_rate: number | null;
  open_cases: number;
  reviewed_cases: number;
  total_cases: number;
  case_status_counts: Record<string, number>;
  discrepancy_types: Record<string, number>;
  document_types: Record<string, number>;
  categories: string[];
  low_confidence_documents: number;
  extraction_methods: Record<string, number>;
  last_run_at: string | null;
};

export type CaseDocumentRef = { document_id: string; source_name: string; document_type: string; amount: number | null; date: string | null };
export type CaseRow = {
  case_id: string;
  case_type: string;
  status: string;
  computed_status: string;
  relationship?: string;
  discrepancy_types: string[];
  explanation: string;
  transaction_id: string;
  documents: CaseDocumentRef[];
  updated_at: string;
};
export type FieldResult = {
  field: string;
  status: string;
  left_value: unknown;
  right_value: unknown;
  difference: number | null;
  difference_percent: number | null;
  discrepancy_type: string | null;
  note?: string;
};
export type SourceField = { field_id: string; label: string; value: unknown; confidence: number | null };
export type SourceView = {
  document_id: string;
  source_name: string;
  source_row: number | null;
  extraction_method: string;
  extraction_confidence: number | null;
  ocr_confidence: number | null;
  low_confidence: boolean;
  page_count: number;
  fields: SourceField[];
};
export type DocumentFacts = {
  document_id: string;
  source_name: string;
  document_type: string;
  identifiers: string[];
  amount: number | null;
  amount_field: { field_id: string; label: string; raw_value: unknown } | null;
  date: string | null;
  date_field: { field_id: string; label: string; raw_value: unknown } | null;
  entity: unknown;
  category: string | null;
  extraction_confidence: number;
};
export type ReviewAction = {
  id: number;
  case_id: string;
  action: "ACCEPT" | "REJECT" | "CORRECT";
  reviewer: string;
  reason: string | null;
  corrected_value: string | null;
  field: string | null;
  created_at: string;
};
export type CaseDetail = Omit<CaseRow, "documents"> & {
  results: FieldResult[];
  evidence?: Record<string, unknown>;
  documents: Array<{ facts: DocumentFacts; source: SourceView | null }>;
  history: ReviewAction[];
};

export type DocumentRow = {
  document_id: string;
  source_name: string;
  source_row: number | null;
  extraction_method: string;
  extraction_confidence: number | null;
  low_confidence: boolean;
  field_count: number;
  transaction_id: string | null;
  document_types: string[] | null;
  kind: string | null;
  category: string | null;
  amount: number | null;
  date: string | null;
  verification_status: string | null;
};
export type DocumentDetail = SourceView & {
  ocr_text: string | null;
  transaction: Record<string, unknown> | null;
  cases: Array<{ case_id: string; status: string; explanation: string }>;
};

export type Breakdown = { label: string; amount: number; count: number };
export type Overview = {
  totals: { revenue: number; expense: number; profit: number; margin: number | null };
  monthly: { months: string[]; revenue: number[]; expense: number[]; profit: number[] };
  revenue_by_category: Breakdown[];
  expense_by_category: Breakdown[];
  top_counterparties: Breakdown[];
  expense_by_counterparty: Breakdown[];
  quarterly: { quarters: string[]; revenue: number[]; expense: number[]; profit: number[]; complete: boolean[] };
  budget: { year: number | null; through_month: number | null; categories: Array<{ category: string; spent: number; budget: number; consumption: number | null; budget_source: string; budget_period?: string }> };
  traceability: { verified_records: number; total_records: number; source_documents: number; date_from: string | null; date_to: string | null; status_counts: Record<string, number>; data_source?: DataSource };
};

export type DataSource = { documents_by_type: Record<string, number>; demo_documents: number; uploaded_documents: number; is_demo: boolean; note: string };
export type Trace = { verified_records: number; date_from: string | null; date_to: string | null; data_source: DataSource };

export type Runway = {
  configured: boolean;
  message?: string;
  error?: string;
  cash_balance?: number;
  cash_as_of?: string;
  cash_source?: string;
  history?: { months: string[]; balance: number[] };
  projection?: { months: string[]; point: number[]; lower: number[]; upper: number[] };
  monthly_net_burn?: number;
  burning_cash?: boolean;
  runway_months?: number | null;
  runway_months_range?: { pessimistic: number | null; optimistic: number | null };
  cash_out_month?: string | null;
  confidence_level?: number;
  method?: string;
  summary?: string;
  traceability?: Trace;
};

export type FinanceSettings = { cash_balance: number | null; cash_as_of: string | null; headcount: number | null; source?: string };
export type Settings = { budgets: Record<string, number>; finance: Partial<FinanceSettings> };

export type Metrics = {
  evaluation: null | {
    generated_at: string;
    h1_extraction: { target: number; results: Array<{ dataset: string; correct: number; fields: number; accuracy: number; meets_target: boolean }> };
    h2_reconciliation: { targets: { precision: number; recall: number }; results: Array<{ dataset: string; genuine_issues: number; flagged: number; true_positives: number; precision: number; recall: number; meets_target: boolean; quality_flags?: number }> };
    h3_forecasting: { error?: string; target_mape?: number; history_months?: number; period?: string[]; metrics?: Record<string, { holdout_6m_mape: Record<string, number | null>; rolling_3m_mape: Record<string, number | null>; meets_target_holdout: boolean; meets_target_rolling: boolean }> };
    h4_review_efficiency: { target: number; demo: Efficiency; by_problem_rate: Array<Efficiency & { problem_share: number }> };
  };
  evaluation_available: boolean;
  how_to_refresh: string;
  live_review_efficiency: Efficiency;
  audit_chain: AuditChain;
  second_ocr_engine: string;
};
export type Efficiency = { documents_needing_reconciliation: number; documents_needing_a_human: number; documents_cleared_automatically: number; reduction: number | null; target: number; meets_target: boolean; method: string; caveat: string };
export type AuditChain = { entries: number; chained: number; legacy_unchained: number; intact: boolean; problems: Array<{ id: number; problem: string }> };

export type ModelForecast = { model: string; point: number[]; lower: number[]; upper: number[]; params?: Record<string, unknown> };
export type Forecast = {
  metric: string;
  error?: string;
  history: { months: string[]; values: number[] };
  forecast_months: string[];
  confidence_level: number;
  models: { linear_regression: ModelForecast; arima: ModelForecast; ensemble: ModelForecast };
  backtest: null | { holdout_months: number; actual: number[]; mape: Record<string, number | null>; interval_coverage: number; target_mape: number };
  rolling_backtest: null | { origins: number; horizon_months: number; mape: Record<string, number | null>; worst_ensemble_mape: number | null; target_mape: number };
  meets_target: boolean;
  traceability?: Trace;
  snapshot_id?: number;
  input_hash?: string;
};

export type ScenarioInput = {
  horizon: number;
  volume_change_pct: number;
  pricing_adjustment_pct: number;
  price_elasticity: number;
  headcount_change: number;
  baseline_headcount: number;
  vendor_consolidation_pct: number;
  other_cost_change_pct: number;
};
type PL = { revenue: number; expense: number; profit: number };
export type ScenarioResult = {
  error?: string;
  assumptions: Record<string, number | string>;
  months: Array<{ month: string; baseline: PL; scenario: PL }>;
  totals: { baseline: PL; scenario: PL; delta: PL };
  budget: { annual_budget: number | null; budget_source: string; window_budget: number | null; baseline_consumption: number | null; scenario_consumption: number | null };
  runway: { configured: boolean; starting_cash: number | null; baseline: CashPath | null; scenario: CashPath | null };
};
type CashPath = { ending_cash: number; runway_months: number | null; burning_cash: boolean };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch {
    throw new Error("The EvoStrategy service is unavailable. Start the backend on port 8000 and try again.");
  }
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch { /* keep generic message */ }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const id = (value: string) => encodeURIComponent(value);

export const api = {
  uploadDocuments: (files: File[]) => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    return request<IngestionJob>("/api/ingestion/jobs", { method: "POST", body: form });
  },
  loadDemo: () => request<IngestionJob>("/api/demo", { method: "POST" }),
  job: (jobId: string) => request<IngestionJob>(`/api/ingestion/jobs/${jobId}`),
  summary: () => request<Summary>("/api/summary"),
  cases: (status?: string) => request<CaseRow[]>(`/api/cases${status ? `?status=${status}` : ""}`),
  caseDetail: (caseId: string) => request<CaseDetail>(`/api/cases/${id(caseId)}/detail`),
  review: (caseId: string, body: { action: string; reviewer: string; reason?: string; field?: string; corrected_value?: string }) =>
    request<CaseDetail>(`/api/cases/${id(caseId)}/review`, json(body)),
  audit: () => request<ReviewAction[]>("/api/audit"),
  documents: () => request<DocumentRow[]>("/api/documents"),
  document: (documentId: string) => request<DocumentDetail>(`/api/documents/${id(documentId)}`),
  pageUrl: (documentId: string, page: number) => `${API_BASE_URL}/api/documents/${id(documentId)}/pages/${page}`,
  overview: () => request<Overview>("/api/analytics/overview"),
  forecast: (metric: string, horizon: number) => request<Forecast>(`/api/forecast?metric=${metric}&horizon=${horizon}`),
  whatif: (input: ScenarioInput) => request<ScenarioResult>("/api/whatif", json(input)),
  runway: () => request<Runway>("/api/runway"),
  settings: () => request<Settings>("/api/settings"),
  saveSettings: (body: Partial<{ budgets: Record<string, number>; finance: Partial<FinanceSettings> }>) =>
    request<Settings>("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  metrics: () => request<Metrics>("/api/metrics"),
  auditChain: () => request<AuditChain>("/api/audit/verify"),
};

export const money = (value: number | null | undefined, compact = false) =>
  value === null || value === undefined
    ? "—"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        notation: compact ? "compact" : "standard",
        maximumFractionDigits: compact ? 1 : 2,
      }).format(value);

export const percent = (value: number | null | undefined, digits = 0) =>
  value === null || value === undefined ? "—" : `${(value * 100).toFixed(digits)}%`;

export const humanize = (value: string | null | undefined) =>
  value ? value.toLowerCase().replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()) : "—";

export const monthLabel = (month: string) => {
  const [year, m] = month.split("-");
  if (m?.startsWith("Q")) return `${m} ${year.slice(2)}`;   // "2012-Q3" -> "Q3 12"
  return `${["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][Number(m) - 1]} ${year.slice(2)}`;
};
