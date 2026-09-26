// Shapes of the MSA HTTP API. The source of truth is src/msa/contracts/* and
// src/msa/api/run_service.py; the run endpoints return plain dicts, so optional keys are many.

export type Role = 'analyst' | 'risk_manager' | 'admin' | 'demo';
export type Mode = 'production' | 'demo';

export interface Me {
  actor: string;
  role: Role;
  scopes: string[];
  expires_at: string;
  llm?: LlmInfo;
}

/** Which language model answers: a local server, the external DeepSeek API or a fixture. */
export interface LlmInfo {
  provider?: 'local' | 'deepseek' | 'mock' | string;
  model?: string | null;
  base_url?: string | null;
  external?: boolean;
}

export type RunState =
  | 'queued'
  | 'running'
  | 'human_fix_graph'
  | 'human_approval'
  | 'completed'
  | 'rejected'
  | 'failed';

export interface RunRow {
  run_id: string;
  event_text: string;
  created_at: string;
  updated_at?: string | null;
  approved_by?: string | null;
  approved_at?: string | null;
  status: RunState;
  error?: string | null;
  portfolio_id: string;
  workflow_id?: string;
  created_by?: string | null;
}

export interface Violation {
  rule_id?: string;
  ok?: boolean;
  path?: string;
  message?: string;
}

export interface Decision {
  outcome: 'approved' | 'returned' | 'rejected';
  reason?: string | null;
  by?: string | null;
  at?: string | null;
}

export interface FixGraphStop {
  kind: 'human_fix_graph';
  graph?: Graph | null;
  attempts?: number;
  violations?: Violation[];
  macro_parameters?: Record<string, ScenarioParameter> | null;
  scenario_required?: boolean;
  decision?: Decision | null;
}

export interface ApprovalStop {
  kind: 'human_approval';
  report?: Report;
  error?: string | null;
}

export interface Interrupt {
  id: string;
  payload: FixGraphStop | ApprovalStop | Record<string, unknown>;
}

export interface RunStatus {
  run_id: string;
  status: RunState;
  pending_interrupt?: Interrupt[];
  errors?: string[];
  node?: string | null;
  attempt?: number;
  error?: string | null;
  report_url?: string | null;
  workflow_id?: string;
  workflow_version?: string;
  plugins?: Record<string, string>;
  snapshot_id?: string | null;
  scenario_id?: string | null;
  macro_draws_sha256?: string | null;
}

export interface Evidence {
  kind: 'document' | 'historical_estimate' | 'expert_assumption';
  source_id: string;
  locator: string;
  fragment_sha256: string;
  author?: string | null;
  as_of?: string | null;
}

export type Distribution =
  | { family: 'point'; value: number }
  | { family: 'triangular'; low: number; mode: number; high: number }
  | { family: 'uniform'; low: number; high: number }
  | { family: 'lognormal'; mu: number; sigma: number };

export type NodeKind = 'event' | 'channel' | 'sector' | 'factor';

export interface GraphNode {
  id: string;
  kind: NodeKind;
  label: string;
  okved?: string | null;
  /** A registered factor; direct factors also identify an instance by key. */
  factor?: string | null;
  key?: string | null;
}

export interface GraphEdge {
  src: string;
  dst: string;
  sign: 1 | -1;
  elasticity: Distribution;
  lag_months: number;
  evidence: Evidence[];
}

export interface Graph {
  event_id: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  factor_elasticity: Record<string, number>;
}

export type ScenarioKind = 'point' | 'triangular' | 'uniform' | 'truncated_normal';
export type ScenarioUnit = 'fraction' | 'days' | 'dimensionless' | 'log_return';

export interface ScenarioParameter {
  label: string;
  evidence: Evidence[];
  kind: ScenarioKind;
  value?: number;
  low?: number;
  mode?: number;
  high?: number;
  mean?: number;
  sigma?: number;
  unit: ScenarioUnit;
  /** A registered factor; a graph-scope factor enters through channel, a direct one by key. */
  factor: string | null;
  key?: string | null;
  channel: string | null;
}

export interface Fragment {
  locator: string;
  text: string;
  sha256: string;
}

export interface SourceDocument {
  doc_id: string;
  status?: string;
  fragments: Fragment[];
}

export interface Parameter {
  value: number;
  unit: string;
  evidence: Evidence[];
}

export interface Passport {
  event_type?: string;
  authority?: string | null;
  act_reference?: string | null;
  effective_date?: string | null;
  territory?: string | null;
}

export interface ScenarioPlan {
  text?: string | null;
  passport?: Passport | null;
  numbers?: Record<string, Parameter> | null;
  parameters?: Record<string, ScenarioParameter> | null;
  confirmed?: boolean;
  required?: boolean;
}

/** One number of a result: a deterministic value, a distribution (P5/P50/P95), or both. */
export interface MetricValue {
  metric_id: string;
  unit: string;
  value?: number | null;
  quantiles?: Quantiles | null;
}

export interface Quantiles {
  name: string;
  unit: string;
  p05: number;
  p50: number;
  p95: number;
  es95?: number | null;
}

export interface Diagnostic {
  code: string;
  severity: 'error' | 'warning' | 'info';
  message?: string;
  path?: string;
}

export interface AggregationContribution {
  slice_id: string;
  measure: string;
  unit: string;
  horizon: number;
  scenario_id: string;
  exposure: number | null;
  exposure_basis: string;
  admission: string;
}

/** The result of one position under the approved scenario set (contracts/result.py). */
export interface CalculationResult {
  position_id: string;
  instrument_id: string;
  instrument_type: string;
  plugin_id: string;
  plugin_version: string;
  model_id: string;
  model_version: string;
  as_of: string;
  horizon: number;
  seed: number;
  base_currency: string;
  scenario_id?: string | null;
  snapshot_id?: string | null;
  macro_draws_sha256?: string | null;
  execution: 'completed' | 'not_run' | 'failed';
  applicability: string;
  data_quality: { score?: number | null; level: 'high' | 'medium' | 'low' | 'unknown'; issues: string[] };
  status: 'ok' | 'uncalibrated' | 'needs_review' | 'incomplete' | 'invalid' | string;
  metrics: Record<string, MetricValue>;
  /** The plugin's own result; its view (ResultView) says how to show it. */
  details: Record<string, unknown>;
  details_schema?: string | null;
  input_sources: Record<string, string[]>;
  sources: Evidence[];
  assumptions: string[];
  flags: string[];
  diagnostics: Diagnostic[];
  limits?: { approved_uses?: string[]; prohibited_uses?: string[]; note?: string };
  contributions: AggregationContribution[];
  model_versions: Record<string, string>;
}

export interface ExcludedPosition {
  position_id: string;
  status: string;
  reason: string;
}

export interface PositionContribution {
  position_id: string;
  mean_loss: number;
  expected_shortfall_contribution: number;
  p95_standalone: number;
}

export interface Coverage {
  basis: string;
  covered_share: number;
  limit: number;
  unknown_exposure: string[];
}

/** One portfolio slice: one measure, summed by realisation, never added to another slice. */
export interface SliceResult {
  slice_id: string;
  measure: string;
  unit: string;
  status: 'ok' | 'needs_review' | 'incomplete' | 'invalid';
  loss_quantiles?: Quantiles | null;
  mean_loss?: number | null;
  value_at_risk_95?: number | null;
  expected_shortfall_95?: number | null;
  coverage: Coverage;
  herfindahl: number;
  included: string[];
  excluded: ExcludedPosition[];
  contributions: PositionContribution[];
  sum_of_individual_p95?: number | null;
  flags: string[];
}

export interface PortfolioResult {
  run_id: string;
  as_of: string;
  horizon: number;
  base_currency: string;
  scenario_id: string;
  slices: Record<string, SliceResult>;
  not_aggregated: ExcludedPosition[];
  status: 'ok' | 'needs_review' | 'incomplete' | 'invalid';
  flags: string[];
}

export interface Party {
  party_id: string;
  name: string;
  kind: string;
  okved?: string | null;
  country?: string | null;
  description?: string | null;
}

export interface Instrument {
  instrument_id: string;
  instrument_type: string;
  name: string;
  currency: string;
  issuer_id?: string | null;
  terms: Record<string, unknown>;
  schema_version: string;
}

export interface Position {
  position_id: string;
  instrument_id: string;
  params: Record<string, unknown>;
  schema_version: string;
  model_id?: string | null;
}

/** A position with its instrument and issuer, as a run reads it. */
export interface PositionContext {
  portfolio_id: string;
  base_currency: string;
  position: Position;
  instrument: Instrument;
  issuer?: Party | null;
}

export interface PortfolioBundle {
  portfolio: {
    portfolio_id: string;
    name: string;
    base_currency: string;
    as_of?: string | null;
    snapshot_id?: string | null;
  };
  parties: Party[];
  instruments: Instrument[];
  positions: Position[];
}

export interface WorkflowNode {
  node: string;
  label: string;
  human?: boolean;
  branch?: string | null;
  plugin: boolean;
  version: string;
  point?: string;
}

/** An agent plugin: the extension point it joins per workflow, and whether it is on. */
export interface WorkflowAgent {
  agent_id: string;
  version: string;
  label: string;
  description?: string;
  extends: Record<string, string>;
  enabled: boolean;
}

/** The execution graph as the screens show it: stages of nodes, extension points, agents. */
export interface WorkflowView {
  workflow_id: string;
  version: string;
  label: string;
  description?: string;
  stages: { stage_id: string; title: string; nodes: WorkflowNode[] }[];
  extension_points: { point_id: string; label: string; agents: string[] }[];
  agents?: WorkflowAgent[];
}

export interface Artifacts {
  scenario_warnings?: Violation[];
  run_id: string;
  status: RunState;
  portfolio_id?: string | null;
  base_currency?: string;
  as_of?: string;
  event_text?: string | null;
  scenario?: ScenarioPlan | null;
  approved_by?: string | null;
  approved_at?: string | null;
  position_names?: Record<string, string> | null;
  graph?: Graph | null;
  document?: SourceDocument | null;
  positions?: PositionContext[] | null;
  /** Position id -> why the scenario reaches it (graph_sector:<okved>, factor:<parameter>). */
  reach?: Record<string, string[]>;
  diagnostics?: Record<string, { items: Diagnostic[]; exposures: Record<string, number | null> }>;
  results?: CalculationResult[] | null;
  portfolio?: PortfolioResult | null;
  /** The keyed view of the results the report cites: metric paths resolve against it. */
  metric_tree?: Record<string, unknown> | null;
  /** Outputs of agent plugins, one namespace per agent. */
  extensions?: Record<string, Record<string, unknown>>;
  workflow?: WorkflowView | null;
  plugins?: Record<string, string>;
  models?: Record<string, string>;
  snapshot?: { snapshot_id: string; as_of: string; label: string; kind: string; sha256: string } | null;
  /** What each plugin states about the run's namespace (the credit calibration in force). */
  notes?: Record<string, Record<string, unknown>>;
}

export interface Recommendation {
  position_id: string;
  action: string;
  rule_id: string;
  metric_refs: string[];
}

export interface NumberRef {
  value: number;
  metric_path: string;
  rounding: number;
}

export interface Report {
  run_id: string;
  summary: string;
  recommendations: Recommendation[];
  assumptions: Evidence[];
  sources: Evidence[];
  numbers: NumberRef[];
  results?: CalculationResult[];
  portfolio?: PortfolioResult | null;
  mode?: Mode;
  approved_by?: string | null;
  approved_at?: string | null;
}

export interface TraceNumber {
  metric_path: string;
  value: number;
  node: string;
  number_ref: NumberRef;
  lineage: { node: string; attempt?: number }[];
  sources: Evidence[];
}

export interface Trace {
  run_id: string;
  numbers: TraceNumber[];
}

export interface PortfolioRow {
  portfolio_id: string;
  name?: string | null;
  base_currency?: string;
  as_of?: string | null;
  snapshot_id?: string | null;
  builtin?: boolean;
  created_at?: string | null;
  expires_at?: string | null;
  positions?: number;
}

/** A position typed in the editor: values and tables by the fields of its type's editor. */
export interface DraftPosition {
  position_id: string;
  name: string;
  instrument_type: string;
  okved?: string | null;
  currency: string;
  values: Record<string, unknown>;
  tables: Record<string, Record<string, unknown>[]>;
}

/** A portfolio typed in the editor; the server turns each number into a sourced assumption. */
export interface PortfolioDraft {
  name: string;
  base_currency: string;
  positions: DraftPosition[];
}

export interface ActivityItem {
  at: string;
  kind: 'llm' | 'tool';
  status: string;
  node?: string | null;
  attempt?: number | null;
  name?: string | null;
  /** Who asked for the call: the workflow itself or an LLM choosing a tool. */
  initiator?: 'workflow' | 'llm';
  details: {
    call_id?: string | null;
    input_sha256?: string;
    output_sha256?: string;
    provider?: string;
    model?: string;
    schema?: string;
    purpose?: string;
    duration_ms?: number;
    prompt_tokens?: number | null;
    completion_tokens?: number | null;
    reasoning_tokens?: number | null;
    error?: string;
  };
}

/** The LLM answers and MCP tool calls of a run. */
export interface Activity {
  run_id: string;
  llm: { calls: number; failed: number; prompt_tokens: number; completion_tokens: number; duration_ms: number };
  tools: { calls: number; failed: number; by_llm?: number; duration_ms: number };
  items: ActivityItem[];
}

export interface LibraryEvent {
  event_id: string;
  title: string;
  text: string;
  metadata?: {
    scenario_text?: string;
    default_start?: boolean;
    portfolio_id?: string;
    description?: string;
    sources?: { source_id: string; title: string; url: string }[];
  } | null;
}

export type EventInput =
  | { kind: 'text'; text: string }
  | { kind: 'url'; url: string }
  | { kind: 'doc_id'; doc_id: string }
  | { kind: 'library'; id: string };

export interface SectorEffect {
  parameter: string;
  label: string;
  okved: string;
  sector: string;
  factor: string;
  shock: number;
  unit: ScenarioUnit;
}

export interface ScenarioCheck {
  violations: Violation[];
  effects: SectorEffect[];
  /** Channel -> the graph factors it reaches. */
  factors: Record<string, string[]>;
}

export interface ToolUse {
  call_id: string;
  name: string;
  arguments: Record<string, unknown>;
  ok: boolean;
  error?: string | null;
}

/** The answer to a question about a calculated run (contracts/explanation.py). */
export interface ExplanationAnswer {
  run_id: string;
  question: string;
  mode: 'llm' | 'structured';
  text: string;
  sections: { title: string; lines: string[] }[];
  numbers: { text: string; tool: string; source_value: number; scaled: boolean }[];
  unverified: string[];
  tool_calls: ToolUse[];
  rounds: number;
  fallback_reason?: string | null;
  model?: string | null;
  prompt_version: string;
  extensions?: Record<string, unknown>;
}

export interface Explanation {
  explanation_id: string;
  run_id: string;
  question: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  answer?: ExplanationAnswer | null;
  error?: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}
