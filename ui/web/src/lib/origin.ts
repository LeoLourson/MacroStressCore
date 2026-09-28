// What a number of the report rests on, in the analyst's terms: how it was reached, the
// words of the event document it cites and the position data it used, by source. The
// scenario itself is not repeated here: it is on the scenario tab. The trace names sources
// by locator and hash; they are matched here to the inputs of the run's positions.
import { metricLabel, sliceSpec } from '../api/catalog';
import type { Artifacts, CalculationResult, TraceNumber } from '../api/types';
import { positionTitle, shorten, unescapeToken } from './format';
import { bySource, positionInputs, sourceKey, type SourceView } from './sources';

export interface OriginQuote {
  where: string;
  text: string;
}

export interface OriginView {
  how: string;
  quotes: OriginQuote[];
  /** The position's data the number used, by source. */
  data: SourceView[];
  /** A portfolio number rests on every included position: named here, detailed per position. */
  positions: string[];
  /** The position whose calculation the number belongs to. */
  positionId: string | null;
}

const SHOWN_INPUTS = 8;

const QUANTILE_WORDS: Record<string, string> = {
  p05: 'P5 — в 5 % сценариев значение ниже',
  p50: 'медиана',
  p95: 'P95 — в 5 % сценариев значение выше',
};

function parts(path: string): string[] {
  return path.replace(/^\/+|\/+$/g, '').split('/').map(unescapeToken);
}

/** The metric a key of a result's own tree stands for: «delta_pd» is «credit.delta_pd». */
function metricOf(result: CalculationResult | undefined, key: string): string | null {
  if (!result) return null;
  if (result.metrics[key]) return key;
  return Object.keys(result.metrics).find((id) => id.endsWith(`.${key}`)) ?? null;
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
  if (p[0] === 'positions') {
    const result = artifacts?.results?.find((r) => r.position_id === p[1]);
    const model = result ? `Модель ${result.model_id}` : 'Модель';
    // A distribution over the shared scenarios: a declared metric or a plugin's own quantiles.
    const metric = p[2] === 'metrics' || p[2] === 'quantiles' ? metricOf(result, p[3]) : null;
    if (metric) {
      const what = metricLabel(metric).toLowerCase();
      if (last === 'value') return `${model} рассчитала значение «${what}».`;
      if (last === 'es95') return `${model} посчитала «${what}» в каждом общем сценарии; взято среднее по 5 % худших.`;
      return `${model} посчитала «${what}» в каждом из общих сценариев; показано: ${QUANTILE_WORDS[last] ?? last}.`;
    }
    return `${model} рассчитала это значение по сценарию события.`;
  }
  return 'Результат расчёта модели позиции по сценарию события.';
}

/** A fragment of the analyst's scenario: «scenario/s2», or «scenario» of older runs. */
export function isScenario(locator: string): boolean {
  return locator === 'scenario' || locator.startsWith('scenario/');
}

/**
 * Where a fragment stands, in words: «Сценарий, предложение 3», «Текст события, абзац 2,
 * предложение 1». A page or a paragraph is named only when the text has more than one.
 */
export function fragmentPlace(locator: string, fragments: { locator: string }[] = []): string {
  if (locator === 'scenario') return 'Сценарий, весь текст';
  const sentence = /\/s(\d+)$/.exec(locator)?.[1];
  const parts = [isScenario(locator) ? 'Сценарий' : 'Текст события'];
  const [, page, rest = ''] = /^p(\d+)\/(.*)$/.exec(locator) ?? [];
  const pages = new Set(fragments.map((f) => /^p(\d+)\//.exec(f.locator)?.[1]).filter(Boolean));
  const paragraphs = new Set(fragments.map((f) => /^p\d+\/para\d+/.exec(f.locator)?.[0]).filter(Boolean));
  const paragraph = /^para(\d+)/.exec(rest)?.[1];
  const table = /^t(\d+)\/r(\d+)/.exec(rest);
  if (page && pages.size > 1) parts.push(`стр. ${page}`);
  if (paragraph && paragraphs.size > 1) parts.push(`абзац ${paragraph}`);
  if (table) parts.push(`таблица ${table[1]}, строка ${table[2]}`);
  if (sentence) parts.push(`предложение ${sentence}`);
  return parts.join(', ');
}

export function describeOrigin(entry: TraceNumber, artifacts: Artifacts): OriginView {
  const documentId = artifacts.document?.doc_id;
  const all = artifacts.document?.fragments ?? [];
  const fragments = new Map(all.map((f) => [f.locator, f.text]));
  const p = parts(entry.metric_path);
  const quotes: OriginQuote[] = [];
  const seen = new Set<string>();
  for (const e of entry.sources) {
    // The scenario's own wording is the scenario tab's; only the event's words are quoted.
    if (e.kind !== 'document' || e.source_id !== documentId || isScenario(e.locator)) continue;
    const text = fragments.get(e.locator);
    if (text && !seen.has(e.locator)) {
      seen.add(e.locator);
      quotes.push({ where: fragmentPlace(e.locator, all), text: shorten(text, 240) });
    }
  }

  if (p[0] === 'portfolio') {
    const included = artifacts.portfolio?.slices[p[2]]?.included ?? [];
    return {
      how: howObtained(entry.metric_path, artifacts),
      quotes,
      data: [],
      positions: [...new Set(included)].sort().map((id) => positionTitle(id, artifacts.position_names)),
      positionId: null,
    };
  }

  const positionId = p[0] === 'positions' ? p[1] : null;
  const used = new Set(entry.sources.map(sourceKey));
  const inputs = positionId
    ? positionInputs(
        artifacts.positions?.find((c) => c.position.position_id === positionId),
        artifacts.results?.find((r) => r.position_id === positionId),
      ).filter((input) => used.has(sourceKey(input.evidence)))
    : [];
  return {
    how: howObtained(entry.metric_path, artifacts),
    quotes,
    data: bySource(inputs, artifacts.position_names, SHOWN_INPUTS),
    positions: [],
    positionId,
  };
}
