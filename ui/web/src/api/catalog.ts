// What the plugins installed on the server declare (GET /v1/asset-types): instrument types
// with their schemas, editor forms and result views; metrics, factors and portfolio slices;
// flags, actions and rules in words. The screens are built from it, so a new plugin on the
// server needs no change in this app; a UI plugin (src/plugins) only adds a richer view.
import { ACTIONS, AUTHORS, FLAG_TABLE, INSTRUMENT_TYPES, RULES, SOURCES } from '../lib/labels';

export type FieldKind = 'number' | 'text' | 'date' | 'dates' | 'enum' | 'boolean' | 'table';

export interface EditorField {
  name: string;
  label: string;
  /** terms, position or snapshot:<kind>: the part of the data the value is stored in. */
  target: string;
  /** A unit of the platform (fraction, days, RUB_million…) or base_money. */
  unit: string | null;
  kind: FieldKind;
  required: boolean;
  default: unknown;
  /** Set when the default stands in for missing data: the result discloses it. */
  assumption: string | null;
  hint: string;
  advanced: boolean;
  minimum: number | null;
  maximum: number | null;
  options: [string, string][];
  columns: EditorField[];
  derive_from?: string | null;
  derived_values?: [string, string][];
}

export interface EditorGroup {
  group_id: string;
  title: string;
  fields: EditorField[];
  folded: boolean;
}

export interface ViewBlock {
  kind: 'metrics' | 'series' | 'table' | 'histogram' | 'sources' | string;
  title: string;
  metric_ids: string[];
  /** A JSON pointer into the result's details. */
  path: string;
  columns: [string, string][];
  hint: string;
}

export interface ResultView {
  view_id: string;
  instrument_types: string[];
  /** A UI plugin's component; without one the standard view renders the blocks. */
  component: string | null;
  blocks: ViewBlock[];
  summary_metrics: string[];
  labels: Record<string, string>;
}

export interface InstrumentTypeSpec {
  asset_type: string;
  label: string;
  description: string;
  plugin_id: string;
  plugin_version: string;
  schema_version: string;
  issuer_required: boolean;
  default_model: string;
  models: { model_id: string; version: string; label: string }[];
  terms_schema: Record<string, unknown>;
  position_schema: Record<string, unknown>;
  editor: EditorGroup[];
  metrics: string[];
  factors: string[];
  slices: string[];
  view: ResultView | null;
}

export interface MetricSpec {
  metric_id: string;
  label: string;
  unit: string;
  kind: 'distribution' | 'value';
  period: string;
  direction: 'higher_is_worse' | 'lower_is_worse' | 'neutral';
  aggregation: string;
  description: string;
  decimals: number;
}

export interface FactorSpec {
  factor_id: string;
  label: string;
  unit: 'fraction' | 'days' | 'log_return';
  scope: 'graph' | 'global' | 'sector' | 'instrument' | 'currency_pair';
  application: string;
  quantity: string;
  temporal: string;
  key_label: string;
  description: string;
  lower_bound: number | null;
}

export interface SliceSpec {
  slice_id: string;
  label: string;
  measure_label: string;
  exposure_basis: string;
  exposure_label: string;
  unit: string;
  coverage_limit: number;
  description: string;
}

export interface RuleSpec {
  rule_id: string;
  label: string;
  observation: string;
  operator: string;
  threshold: number;
  actions: string[];
  unit: string | null;
}

export interface Catalog {
  sdk_version: string;
  plugins: { plugin_id: string; version: string; label: string; description: string }[];
  types: InstrumentTypeSpec[];
  metrics: Record<string, MetricSpec>;
  factors: Record<string, FactorSpec>;
  slices: Record<string, SliceSpec>;
  actions: Record<string, string>;
  rules: Record<string, RuleSpec>;
  flags: Record<string, string>;
  units: { plain: string[]; currencies: string[] };
  sources: Record<string, string>;
  authors: Record<string, string>;
}

let catalog: Catalog = {
  sdk_version: '',
  plugins: [],
  types: [],
  metrics: {},
  factors: {},
  slices: {},
  actions: {},
  rules: {},
  flags: {},
  units: { plain: [], currencies: [] },
  sources: {},
  authors: {},
};

/** Read once before the app renders; without it the screens show identifiers. */
export async function loadCatalog(): Promise<void> {
  try {
    const response = await fetch('/v1/asset-types');
    if (response.ok) setCatalog((await response.json()) as Catalog);
  } catch {
    // The API is down: the sign-in page says so; nothing here to show.
  }
}

export function setCatalog(value: Catalog): void {
  catalog = value;
  for (const item of value.types) INSTRUMENT_TYPES[item.asset_type] = item.label;
  Object.assign(ACTIONS, value.actions);
  for (const [id, rule] of Object.entries(value.rules)) RULES[id] = rule.label;
  Object.assign(FLAG_TABLE, value.flags);
  Object.assign(SOURCES, value.sources);
  Object.assign(AUTHORS, value.authors);
}

export function getCatalog(): Catalog {
  return catalog;
}

export function instrumentTypes(): InstrumentTypeSpec[] {
  return catalog.types;
}

export function typeSpec(typeId: string): InstrumentTypeSpec | undefined {
  return catalog.types.find((item) => item.asset_type === typeId);
}

export function metricSpec(metricId: string): MetricSpec | undefined {
  return catalog.metrics[metricId];
}

export function metricLabel(metricId: string): string {
  return catalog.metrics[metricId]?.label ?? metricId;
}

export function factorSpec(factorId: string | null | undefined): FactorSpec | undefined {
  return factorId ? catalog.factors[factorId] : undefined;
}

export function factorLabel(factorId: string | null | undefined): string {
  if (!factorId) return '—';
  return catalog.factors[factorId]?.label ?? factorId;
}

/** Factors of the graph scope, in the order the plugins declare them. */
export function graphFactors(): FactorSpec[] {
  return Object.values(catalog.factors).filter((f) => f.scope === 'graph');
}

/** Factors applied directly to instruments by a key (a market index, a currency pair). */
export function directFactors(): FactorSpec[] {
  return Object.values(catalog.factors).filter((f) => f.scope !== 'graph');
}

export function sliceSpec(sliceId: string): SliceSpec | undefined {
  return catalog.slices[sliceId];
}

export function viewFor(typeId: string): ResultView | null {
  return typeSpec(typeId)?.view ?? null;
}
