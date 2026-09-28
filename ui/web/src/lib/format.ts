// Russian number, date and phrase formatting.
import { factorLabel, metricLabel, sliceSpec, viewFor } from '../api/catalog';
import type { Distribution, Graph, PositionContext, ScenarioParameter } from '../api/types';
import { INSTRUMENT_TYPES, label } from './labels';

// A no-break space keeps «1 234,5 млн ₽» on one line.
export const NBSP = ' ';

export function number(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return '—';
  const fixed = Math.abs(value).toFixed(digits);
  const [whole, fraction] = fixed.split('.');
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
  const sign = value < 0 && Number(fixed) !== 0 ? '−' : '';
  return sign + grouped + (fraction ? `,${fraction}` : '');
}

/** Up to four decimals without trailing zeros: 0,06 rather than 0,0600. */
export function compact(value: number | null | undefined): string {
  const text = number(value, 4);
  return text.includes(',') ? text.replace(/0+$/, '').replace(/,$/, '') : text;
}

export function percent(value: number | null | undefined, digits = 1): string {
  if (value == null) return '—';
  return `${number(value * 100, digits)}${NBSP}%`;
}

const CURRENCY_SIGNS: Record<string, string> = { RUB: '₽', USD: '$', EUR: '€', CNY: '¥' };

export function currencySign(currency: string): string {
  return CURRENCY_SIGNS[currency] ?? currency;
}

/** Millions of a currency: «1 234,50 млн ₽». */
export function money(value: number | null | undefined, digits = 2, currency = 'RUB'): string {
  if (value == null) return '—';
  return `${number(value, digits)}${NBSP}млн${NBSP}${currencySign(currency)}`;
}

/** The words of a unit after a number, «млн ₽», «%», «дн.»; empty for a ratio. */
export function unitWords(unit: string | null | undefined): string {
  if (!unit) return '';
  const million = /^([A-Z]{3})_million$/.exec(unit);
  if (million) return `млн ${currencySign(million[1])}`;
  const price = /^([A-Z]{3})_per_unit$/.exec(unit);
  if (price) return `${currencySign(price[1])} за ед.`;
  return (
    {
      fraction: '%',
      percentage_point: 'п.п.',
      basis_point: 'б.п.',
      days: 'дн.',
      months: 'мес.',
      years: 'лет',
      shares: 'шт.',
      count: 'шт.',
      price_per_100: 'за 100 номинала',
      log_return: 'лог. доходн.',
    }[unit] ?? ''
  );
}

/** A number with its unit: money in millions, fractions in percent, days, shares. */
export function metricValue(value: number | null | undefined, unit: string | null | undefined, digits?: number): string {
  if (value == null) return '—';
  const million = unit ? /^([A-Z]{3})_million$/.exec(unit) : null;
  if (million) return money(value, digits ?? 2, million[1]);
  const price = unit ? /^([A-Z]{3})_per_unit$/.exec(unit) : null;
  if (price) return `${number(value, digits ?? 2)}${NBSP}${currencySign(price[1])}`;
  switch (unit) {
    case 'fraction':
      return percent(value, digits ?? 2);
    case 'percentage_point':
      return `${number(value, digits ?? 2)}${NBSP}п.п.`;
    case 'basis_point':
      return `${number(value, digits ?? 1)}${NBSP}б.п.`;
    case 'days':
      return `${number(value, digits ?? 0)}${NBSP}дн.`;
    case 'months':
      return `${number(value, digits ?? 0)}${NBSP}мес.`;
    case 'shares':
    case 'count':
      return number(value, digits ?? 0);
    case 'log_return':
      return number(value, digits ?? 4);
    default:
      return number(value, digits ?? 2);
  }
}

/** The formatter of one unit, for the three quantiles shown together. */
export function formatter(unit: string | null | undefined, digits?: number) {
  return (value: number | null | undefined) => metricValue(value, unit, digits);
}

/** A number as metricValue writes it, without its unit: «1 105,01» of «1 105,01 млн ₽», «5,02» of «5,02 %». */
export function bareValue(value: number | null | undefined, unit: string | null | undefined): string {
  const words = unitWords(unit).replaceAll(' ', NBSP);
  const text = metricValue(value, unit);
  return words && text.endsWith(`${NBSP}${words}`) ? text.slice(0, -words.length - 1) : text;
}

/**
 * A change of a quantity, signed: «+8 053,86 млн ₽». A change of a fraction is in percentage
 * points, «+63,96 п.п.»: «+63,96 %» would read as a relative change.
 */
export function change(value: number | null | undefined, unit: string | null | undefined): string {
  if (value == null) return '—';
  return signed(unit === 'fraction' ? metricValue(value * 100, 'percentage_point') : metricValue(value, unit), value);
}

/** The same change without its unit, for the lower end of a range: «+4 005,29 … +16 385,62 млн ₽». */
export function bareChange(value: number | null | undefined, unit: string | null | undefined): string {
  if (value == null) return '—';
  return signed(unit === 'fraction' ? bareValue(value * 100, 'percentage_point') : bareValue(value, unit), value);
}

// A plus only before a growth that shows in the digits: «+0,55», never «+0,00».
function signed(text: string, value: number): string {
  return value > 0 && /[1-9]/.test(text) ? `+${text}` : text;
}

/** «1 актив», «2 актива», «5 активов». */
export function plural(count: number, one: string, few: string, many: string): string {
  const tens = count % 100;
  if (tens >= 11 && tens <= 14) return `${count} ${many}`;
  switch (count % 10) {
    case 1:
      return `${count} ${one}`;
    case 2:
    case 3:
    case 4:
      return `${count} ${few}`;
    default:
      return `${count} ${many}`;
  }
}

function pad(value: number): string {
  return String(value).padStart(2, '0');
}

function parseMoment(value: string): Date {
  // API times are UTC; values without a zone come from SQLite.
  const zoned = /[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`;
  return new Date(zoned.replace(' ', 'T'));
}

export function timestamp(value: string | null | undefined): string {
  if (!value) return '—';
  const moment = parseMoment(value);
  if (Number.isNaN(moment.getTime())) return value;
  return (
    `${pad(moment.getDate())}.${pad(moment.getMonth() + 1)}.${moment.getFullYear()} ` +
    `${pad(moment.getHours())}:${pad(moment.getMinutes())}`
  );
}

export function day(value: string | null | undefined): string {
  if (!value) return '—';
  const [y, m, d] = value.slice(0, 10).split('-');
  return d && m && y ? `${d}.${m}.${y}` : value;
}

export function approver(name: string | null | undefined): string {
  if (!name) return '—';
  return name === 'demo:auto' ? 'автоматически (демо-режим)' : name;
}

export function lowerFirst(text: string): string {
  return text.slice(0, 1).toLowerCase() + text.slice(1);
}

export function capitalize(text: string): string {
  return text.slice(0, 1).toUpperCase() + text.slice(1);
}

export function positionName(positionId: string, names?: Record<string, string> | null): string {
  const name = names?.[positionId];
  return name && name !== positionId ? name : positionId;
}

export function positionTitle(positionId: string, names?: Record<string, string> | null): string {
  const name = names?.[positionId];
  return name && name !== positionId ? `${name} (${positionId})` : positionId;
}

export function typeName(typeId: string | null | undefined): string {
  return label(INSTRUMENT_TYPES, typeId);
}

export function instrumentLine(context: PositionContext | undefined): string {
  if (!context) return '';
  const parts = [typeName(context.instrument.instrument_type), context.instrument.currency];
  if (context.issuer?.okved) parts.push(`ОКВЭД ${context.issuer.okved}`);
  return parts.join(' · ');
}

/** A scenario distribution in words: «от 6 % до 14 %, чаще 10 %». */
export function scenarioValue(p: Pick<ScenarioParameter, 'kind' | 'unit' | 'value' | 'low' | 'mode' | 'high' | 'mean'>): string {
  const show = (value: number | undefined) => {
    if (value == null) return '—';
    if (p.unit === 'fraction') return `${compact(value * 100)}${NBSP}%`;
    if (p.unit === 'days') return `${compact(value)}${NBSP}дн.`;
    if (p.unit === 'log_return') return `${compact(value * 100)}${NBSP}% (лог.)`;
    return compact(value);
  };
  switch (p.kind) {
    case 'point':
      return show(p.value);
    case 'triangular':
      return `от ${show(p.low)} до ${show(p.high)}, чаще ${show(p.mode)}`;
    case 'uniform':
      return `от ${show(p.low)} до ${show(p.high)}, любое значение`;
    case 'truncated_normal':
      return `около ${show(p.mean)}, от ${show(p.low)} до ${show(p.high)}`;
    default:
      return '—';
  }
}

/** What a scenario parameter moves: a factor through a graph channel, or directly by its key. */
export function parameterTarget(p: Pick<ScenarioParameter, 'factor' | 'key' | 'channel'>, graph?: Graph | null): string {
  const factor = factorLabel(p.factor);
  if (p.key) return `${factor}: ${p.key}`;
  if (p.channel) return `${factor} через канал «${nodeLabels(graph)[p.channel] ?? p.channel}»`;
  return factor;
}

export function elasticityText(e: Distribution): string {
  switch (e.family) {
    case 'point':
      return compact(e.value);
    case 'triangular':
      return `${compact(e.low)}…${compact(e.high)}, чаще ${compact(e.mode)}`;
    case 'uniform':
      return `${compact(e.low)}…${compact(e.high)}`;
    case 'lognormal':
      return `логнорм. μ ${compact(e.mu)}, σ ${compact(e.sigma)}`;
  }
}

/** A node's name for people: an event labelled with a bare identifier reads as «Событие». */
export function nodeName(node: { kind: string; label: string }): string {
  return node.kind === 'event' && /^[A-Z0-9_.:-]+$/.test(node.label) ? 'Событие' : node.label;
}

export function nodeLabels(graph: Graph | null | undefined): Record<string, string> {
  return Object.fromEntries((graph?.nodes ?? []).map((n) => [n.id, nodeName(n)]));
}

export function unescapeToken(token: string): string {
  return token.replace(/~1/g, '/').replace(/~0/g, '~');
}

export function escapeToken(token: string): string {
  return token.replace(/~/g, '~0').replace(/\//g, '~1');
}

/** A metric path of the run's metric tree: /positions/<id>/..., /portfolio/slices/<id>/... */
export function positionPath(positionId: string, ...tail: string[]): string {
  return ['', 'positions', escapeToken(positionId), ...tail.map(escapeToken)].join('/');
}

export function slicePath(sliceId: string, ...tail: string[]): string {
  return ['', 'portfolio', 'slices', escapeToken(sliceId), ...tail.map(escapeToken)].join('/');
}

const QUANTILE: Record<string, string> = {
  p05: 'P5',
  p50: 'медиана (P50)',
  p95: 'P95',
  es95: 'средняя в худших 5 % сценариев (ES95)',
  value: 'значение',
};

const SLICE_FIELDS: Record<string, string> = {
  covered_percent: 'охват расчётом, %',
  expected_shortfall_95: 'средние потери в худших 5 % сценариев (ES95)',
  value_at_risk_95: 'P95 потерь',
  mean_loss: 'средние потери',
  herfindahl: 'концентрация (индекс Херфиндаля)',
  sum_of_individual_p95: 'сумма P95 по позициям',
};

/** A report number's metric path in words: whose number and which quantity. */
export function describePath(
  path: string,
  options: {
    names?: Record<string, string> | null;
    types?: Record<string, string>;
    owner?: boolean;
    /** Plain words for the run's identifiers a path may hold: channels, covenants. */
    words?: Map<string, string>;
  } = {},
): string {
  const { names, types, owner = true, words } = options;
  const parts = path.replace(/^\/+|\/+$/g, '').split('/').map(unescapeToken);
  if (parts[0] === 'portfolio' && parts[1] === 'slices' && parts.length >= 4) {
    const slice = sliceSpec(parts[2]);
    const title = slice?.label ?? parts[2];
    const rest = parts.slice(3);
    let what = rest.join('/');
    if (rest[0] === 'loss_quantiles' && rest.length === 2) {
      what = `${(slice?.measure_label ?? 'потери').toLowerCase()}, ${QUANTILE[rest[1]] ?? rest[1]}`;
    } else if (rest[0] === 'contributions' && rest.length === 3) {
      what = `вклад ${positionTitle(rest[1], names)} в ES95`;
    } else if (SLICE_FIELDS[rest[0]]) {
      what = SLICE_FIELDS[rest[0]];
    }
    return owner ? `${title}: ${what}` : what;
  }
  if (parts[0] !== 'positions' || parts.length < 3) return path;
  const positionId = parts[1];
  const rest = parts.slice(2);
  let what: string;
  if (rest[0] === 'metrics' && rest.length === 3) {
    what = `${metricLabel(rest[1])}, ${QUANTILE[rest[2]] ?? rest[2]}`;
  } else {
    // A plugin's projection of its details: its view names the keys it carries, and a key
    // it names with "" only groups others. A quantile at the end reads after a comma.
    const view = types?.[positionId] ? viewFor(types[positionId]) : null;
    const last = rest[rest.length - 1];
    const quantile = rest.length > 1 && last !== 'value' ? QUANTILE[last] : undefined;
    what = (quantile ? rest.slice(0, -1) : rest)
      .map((token) => view?.labels[token] ?? words?.get(token) ?? token)
      .filter(Boolean)
      .join(' / ');
    if (quantile) what = `${what}, ${quantile}`;
  }
  if (owner) return `${positionTitle(positionId, names)}: ${what}`;
  // Mid-sentence, except abbreviations such as ICR.
  return /^.[a-zа-яё]/.test(what) ? lowerFirst(what) : what;
}

export function resolvePath(tree: unknown, path: string): unknown {
  let node: unknown = tree;
  for (const token of path.replace(/^\/+|\/+$/g, '').split('/')) {
    if (node == null || typeof node !== 'object') return undefined;
    node = (node as Record<string, unknown>)[unescapeToken(token)];
  }
  return node;
}

/** The value behind a metric path of the run's metric tree, formatted with its unit. */
export function pathValue(tree: unknown, path: string): string {
  const value = resolvePath(tree, path);
  if (typeof value !== 'number') return '—';
  const parts = path.replace(/^\/+/, '').split('/').map(unescapeToken);
  const field = parts[parts.length - 1];
  const parent = resolvePath(tree, parts.slice(0, -1).map(escapeToken).join('/')) as { unit?: string } | undefined;
  if (parent?.unit) return metricValue(value, parent.unit);
  if (field === 'covered_percent') return `${number(value)}${NBSP}%`;
  if (field.endsWith('_probability') || field.endsWith('_share')) return percent(value);
  if (field.endsWith('_pp')) return `${number(value)}${NBSP}п.п.`;
  if (field.endsWith('_pct')) return `${number(value)}${NBSP}%`;
  return number(value, Math.abs(value) < 1 ? 4 : 2);
}

export function shorten(text: string | null | undefined, limit: number): string {
  const flat = (text ?? '').split(/\s+/).filter(Boolean).join(' ');
  return flat.length <= limit ? flat : `${flat.slice(0, limit).trimEnd()}…`;
}
