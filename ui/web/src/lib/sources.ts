// The data a run rests on, by source, in the analyst's words: what the source is, of what
// kind, who stands behind it and on what date, and which inputs of which position it gave.
// An input is named by the field its locator ends with («SGZH/borrowing_rate» — «ставка по
// долгу»), as the position's editor names it, and grouped as the editor groups it; the view
// of the type names the rest. A position's own parameters carry their values.
import { typeSpec, viewFor } from '../api/catalog';
import type { CalculationResult, Evidence, PositionContext } from '../api/types';
import { capitalize, day, metricValue, positionTitle } from './format';
import { AUTHORS, EVIDENCE_KINDS, SOURCES, label } from './labels';

/** One input of a position and where it came from. */
export interface Input {
  positionId: string;
  typeId: string;
  evidence: Evidence;
  /** The value, when the position's own parameters hold it. */
  value?: string;
}

export interface InputGroup {
  title: string;
  items: string[];
}

export interface SourcePosition {
  positionId: string;
  title: string;
  groups: InputGroup[];
  /** Inputs whose field no editor or view names. */
  unnamed: number;
}

export interface SourceView {
  key: string;
  name: string;
  kind: string;
  author: string | null;
  asOf: string | null;
  count: number;
  positions: SourcePosition[];
}

const OTHER = 'Прочие данные';

interface Parameter {
  value: number;
  unit: string;
  evidence: Evidence[];
}

function isParameter(value: unknown): value is Parameter {
  return (
    !!value &&
    typeof value === 'object' &&
    typeof (value as Parameter).value === 'number' &&
    typeof (value as Parameter).unit === 'string' &&
    Array.isArray((value as Parameter).evidence)
  );
}

export function sourceKey(e: Evidence): string {
  return `${e.source_id}|${e.locator}|${e.fragment_sha256}`;
}

// Mid-list a name starts in lower case, except abbreviations such as LGD or EBITDA.
export function inList(name: string): string {
  return /^.[a-zа-яё]/.test(name) ? name.slice(0, 1).toLowerCase() + name.slice(1) : name;
}

/**
 * The inputs of one position: its own parameters with their values, and the data its model
 * read from the snapshot (the result's sources). Fragments of the event text are not inputs
 * of a position: they ground the scenario.
 */
export function positionInputs(context: PositionContext | undefined, result: CalculationResult | undefined): Input[] {
  const positionId = context?.position.position_id ?? result?.position_id;
  const typeId = context?.instrument.instrument_type ?? result?.instrument_type;
  if (!positionId || !typeId) return [];
  const found = new Map<string, Input>();
  const add = (evidence: Evidence, value?: string) => {
    if (evidence.kind === 'document') return;
    const key = sourceKey(evidence);
    if (!found.has(key) || value) found.set(key, { positionId, typeId, evidence, value });
  };
  const walk = (value: unknown) => {
    if (isParameter(value)) {
      for (const e of value.evidence) add(e, metricValue(value.value, value.unit));
    } else if (Array.isArray(value)) {
      value.forEach(walk);
    } else if (value && typeof value === 'object') {
      Object.values(value).forEach(walk);
    }
  };
  if (context) {
    walk(context.position.params);
    walk(context.instrument.terms);
  }
  for (const e of result?.sources ?? []) add(e);
  return [...found.values()];
}

/** The field a locator names, in words, with the editor group it belongs to. */
function fieldOf(typeId: string, locator: string): { group: string; name: string; order: number } | null {
  const tokens = locator.split('/').slice(1);
  if (!tokens.length) return null;
  const groups = typeSpec(typeId)?.editor ?? [];
  let order = 0;
  for (const group of groups) {
    for (const field of group.fields) {
      order += 1;
      if (field.name === tokens[0] && tokens.length === 1) return { group: group.title, name: field.label, order };
    }
  }
  const labels = viewFor(typeId)?.labels ?? {};
  const [head, tail] = tokens;
  if (tokens.length === 2 && labels[head] && labels[`${head}:${tail}`]) {
    return { group: OTHER, name: `${labels[head]} «${labels[`${head}:${tail}`]}»`, order: order + 1 };
  }
  if (tokens.length === 1 && labels[head]) return { group: OTHER, name: labels[head], order: order + 2 };
  return null;
}

/** The inputs of positions in words, by editor group, at most `limit` per group. */
function describeInputs(inputs: Input[], limit: number): { groups: InputGroup[]; unnamed: number } {
  const byGroup = new Map<string, { order: number; text: string }[]>();
  let unnamed = 0;
  const seen = new Set<string>();
  for (const input of inputs) {
    const field = fieldOf(input.typeId, input.evidence.locator);
    if (!field) {
      unnamed += 1;
      continue;
    }
    const text = input.value ? `${inList(field.name)} ${input.value}` : inList(field.name);
    if (seen.has(text)) continue;
    seen.add(text);
    byGroup.set(field.group, [...(byGroup.get(field.group) ?? []), { order: field.order, text }]);
  }
  const groups = [...byGroup.entries()]
    .map(([title, items]) => ({ title, items: items.sort((a, b) => a.order - b.order), first: Math.min(...items.map((i) => i.order)) }))
    .sort((a, b) => a.first - b.first)
    .map(({ title, items }) => {
      const shown = items.slice(0, limit).map((i) => i.text);
      if (items.length > limit) shown.push(`и ещё ${items.length - limit}`);
      return { title, items: shown };
    });
  return { groups, unnamed };
}

/** Inputs grouped by their source (kind, source, author, date), then by position. */
export function bySource(inputs: Input[], names?: Record<string, string> | null, limit = Infinity): SourceView[] {
  const sources = new Map<string, Input[]>();
  for (const input of inputs) {
    const e = input.evidence;
    const key = [e.kind, e.source_id, e.author ?? '', e.as_of ?? ''].join('|');
    sources.set(key, [...(sources.get(key) ?? []), input]);
  }
  return [...sources.entries()].map(([key, items]) => {
    const e = items[0].evidence;
    const byPosition = new Map<string, Input[]>();
    for (const item of items) byPosition.set(item.positionId, [...(byPosition.get(item.positionId) ?? []), item]);
    return {
      key,
      name: capitalize(label(SOURCES, e.source_id)),
      kind: label(EVIDENCE_KINDS, e.kind),
      author: e.author ? label(AUTHORS, e.author) : null,
      asOf: e.as_of ? day(e.as_of) : null,
      count: items.length,
      positions: [...byPosition.entries()]
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([positionId, own]) => ({ positionId, title: positionTitle(positionId, names), ...describeInputs(own, limit) })),
    };
  });
}

/** «Допущение эксперта · генератор демо-каталога · на 11.09.2026». */
export function sourceMeta(source: SourceView): string {
  return [source.kind, source.author, source.asOf ? `на ${source.asOf}` : null].filter(Boolean).join(' · ');
}
