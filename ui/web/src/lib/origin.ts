// What a number of the report rests on, in the analyst's terms: how it was reached, the
// words of the event it cites, the scenario behind it and the position data it used. The
// trace names sources by locator and hash; they are matched here to the run's own position
// parameters, event fragments and scenario parameters. Data read from the snapshot is named
// by its basis (who, which source, on what date) and its locator.
import { metricLabel, sliceSpec, typeSpec } from '../api/catalog';
import type { Artifacts, Evidence, PositionContext, TraceNumber } from '../api/types';
import { day, metricValue, parameterTarget, positionTitle, scenarioValue, shorten, unescapeToken } from './format';
import { AUTHORS, SOURCES, label } from './labels';

export interface OriginQuote {
  where: string;
  text: string;
}

export interface OriginInputs {
  position: string;
  items: string[];
  more: number;
  bases: string[];
}

export interface OriginView {
  how: string;
  quotes: OriginQuote[];
  scenario: string[];
  inputs: OriginInputs[];
  /** Data of the snapshot and other sources, by basis. */
  data: string[];
  /** A portfolio number rests on every included position: named here, detailed per position. */
  positions: string[];
}

const SHOWN_INPUTS = 8;

const QUANTILE_WORDS: Record<string, string> = {
  p05: 'P5 — в 5 % сценариев значение ниже',
  p50: 'медиана',
  p95: 'P95 — в 5 % сценариев значение выше',
};

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

function sourceKey(e: Evidence): string {
  return `${e.source_id}|${e.locator}|${e.fragment_sha256}`;
}

/** Who and on what basis: «составитель демо-данных, демо-данные техзадания, на 11.09.2026». */
export function basisText(e: Evidence): string {
  const who = e.author ? label(AUTHORS, e.author) : null;
  const what = label(SOURCES, e.source_id);
  return [who, what, e.as_of ? `на ${day(e.as_of)}` : null].filter(Boolean).join(', ');
}

// Mid-list a name starts in lower case, except abbreviations such as LGD or EBITDA.
function inList(name: string): string {
  return /^.[a-zа-яё]/.test(name) ? name.slice(0, 1).toLowerCase() + name.slice(1) : name;
}

type Input = { positionId: string; text: string; rank: number };

/** Field name -> its label, from the editor form the instrument type declares. */
function fieldLabels(typeId: string): Record<string, string> {
  const labels: Record<string, string> = {};
  for (const group of typeSpec(typeId)?.editor ?? []) {
    for (const field of group.fields) labels[field.name] = field.label;
  }
  return labels;
}

/** Every sourced parameter of the positions' terms and params, by the key of its sources. */
function positionInputs(positions: PositionContext[]): Map<string, Input> {
  const index = new Map<string, Input>();
  for (const context of positions) {
    const labels = fieldLabels(context.instrument.instrument_type);
    let rank = 0;
    const walk = (value: unknown, name: string) => {
      if (isParameter(value)) {
        rank += 1;
        const text = `${inList(labels[name] ?? name)} ${metricValue(value.value, value.unit)}`;
        for (const e of value.evidence) index.set(sourceKey(e), { positionId: context.position.position_id, text, rank });
      } else if (Array.isArray(value)) {
        value.forEach((item) => walk(item, name));
      } else if (value && typeof value === 'object') {
        for (const [key, inner] of Object.entries(value)) walk(inner, key);
      }
    };
    walk(context.position.params, 'params');
    walk(context.instrument.terms, 'terms');
  }
  return index;
}

function fragmentPlace(locator: string): string {
  if (locator === 'scenario') return 'Формулировка сценария';
  const paragraph = /para(\d+)/.exec(locator);
  return paragraph ? `Текст события, абзац ${paragraph[1]}` : 'Текст события';
}

function parts(path: string): string[] {
  return path.replace(/^\/+|\/+$/g, '').split('/').map(unescapeToken);
}

/** How the number was reached, from what its metric path names. */
export function howObtained(path: string, artifacts?: Artifacts): string {
  const p = parts(path);
  const last = p[p.length - 1];
  if (p[0] === 'portfolio' && p[1] === 'slices') {
    const slice = sliceSpec(p[2]);
    if (p[3] === 'loss_quantiles' && last === 'es95') {
      return 'Потери позиций среза сложены в каждом общем сценарии; взято среднее по 5 % худших сценариев.';
    }
    if (p[3] === 'loss_quantiles') {
      return `Потери позиций среза сложены в каждом общем сценарии; показан квантиль суммы: ${QUANTILE_WORDS[last] ?? last}.`;
    }
    if (p[3] === 'covered_percent') {
      return `Доля ${(slice?.exposure_label ?? 'размера позиций').toLowerCase()} тех позиций, чьи результаты вошли в итог среза.`;
    }
    if (p[3] === 'contributions') return 'Вклад позиции в ES95 среза на тех же общих сценариях.';
    return 'Итог по срезу портфеля.';
  }
  if (p[0] === 'positions' && p[2] === 'metrics') {
    const result = artifacts?.results?.find((r) => r.position_id === p[1]);
    const model = result ? `Модель ${result.model_id}` : 'Модель';
    const what = metricLabel(p[3]).toLowerCase();
    if (last === 'value') return `${model} рассчитала значение «${what}».`;
    if (last === 'es95') return `${model} посчитала «${what}» в каждом общем сценарии; взято среднее по 5 % худших.`;
    return `${model} посчитала «${what}» в каждом из общих сценариев; показано: ${QUANTILE_WORDS[last] ?? last}.`;
  }
  return 'Результат расчёта модели позиции по сценарию события.';
}

/** The scenario parameters that moved this number: for a position, those that reached it. */
function scenarioLines(path: string, artifacts: Artifacts): string[] {
  const parameters = artifacts.scenario?.parameters ?? {};
  const p = parts(path);
  let names = Object.keys(parameters);
  if (p[0] === 'positions') {
    const reach = artifacts.reach?.[p[1]] ?? [];
    const direct = new Set(reach.filter((r) => r.startsWith('factor:')).map((r) => r.slice('factor:'.length)));
    const viaGraph = reach.some((r) => r.startsWith('graph_sector:'));
    names = names.filter((name) => direct.has(name) || (viaGraph && parameters[name].channel));
  }
  return names.map((name) => {
    const item = parameters[name];
    return `${item.label || name} (${parameterTarget(item, artifacts.graph)}): ${scenarioValue(item)}`;
  });
}

export function describeOrigin(entry: TraceNumber, artifacts: Artifacts): OriginView {
  const documentId = artifacts.document?.doc_id;
  const fragments = new Map((artifacts.document?.fragments ?? []).map((f) => [f.locator, f.text]));
  const inputs = positionInputs(artifacts.positions ?? []);
  const names = artifacts.position_names;
  const quotes: OriginQuote[] = [];
  const seenQuotes = new Set<string>();
  const grouped = new Map<string, { inputs: Map<string, number>; bases: Set<string> }>();
  const data = new Map<string, Set<string>>();

  for (const e of entry.sources) {
    if (e.kind === 'document' && e.source_id === documentId) {
      const text = fragments.get(e.locator);
      if (text && !seenQuotes.has(e.locator)) {
        seenQuotes.add(e.locator);
        quotes.push({ where: fragmentPlace(e.locator), text: shorten(text, 240) });
      }
      continue;
    }
    const input = inputs.get(sourceKey(e));
    if (!input) {
      // Snapshot data: statements, prices, rates, sensitivities.
      const basis = basisText(e);
      data.set(basis, (data.get(basis) ?? new Set()).add(e.locator));
      continue;
    }
    const group = grouped.get(input.positionId) ?? { inputs: new Map(), bases: new Set() };
    group.inputs.set(input.text, input.rank);
    group.bases.add(basisText(e));
    grouped.set(input.positionId, group);
  }

  const portfolio = entry.metric_path.startsWith('/portfolio');
  const titles = portfolio
    ? [...new Set((artifacts.portfolio?.slices[parts(entry.metric_path)[2]]?.included ?? []))]
        .sort()
        .map((id) => positionTitle(id, names))
    : [];
  return {
    how: howObtained(entry.metric_path, artifacts),
    quotes,
    scenario: scenarioLines(entry.metric_path, artifacts),
    inputs: portfolio
      ? []
      : [...grouped.entries()].map(([positionId, group]) => {
          const all = [...group.inputs.entries()].sort((a, b) => a[1] - b[1]).map(([text]) => text);
          return {
            position: positionTitle(positionId, names),
            items: all.slice(0, SHOWN_INPUTS),
            more: Math.max(0, all.length - SHOWN_INPUTS),
            bases: [...group.bases],
          };
        }),
    data: portfolio
      ? []
      : [...data.entries()].map(([basis, locators]) => `${basis}: ${plainLocators([...locators])}`),
    positions: titles,
  };
}

function plainLocators(locators: string[]): string {
  const shown = locators.slice(0, 6).join(', ');
  return locators.length > 6 ? `${shown} и ещё ${locators.length - 6}` : shown;
}
