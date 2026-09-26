// The portfolio editor's inputs, by instrument type, as the plugins declare them (the
// catalog's `editor` groups). Every number the analyst types becomes a sourced assumption on
// the server; a declared default is applied there, with its assumption flag, never here.
import { instrumentTypes, typeSpec, type EditorField, type EditorGroup } from '../api/catalog';
import type { DraftPosition, PortfolioBundle, PortfolioDraft } from '../api/types';
import { currencySign } from './format';

export function groupsOf(typeId: string): EditorGroup[] {
  return typeSpec(typeId)?.editor ?? [];
}

export function fieldsOf(typeId: string): EditorField[] {
  return groupsOf(typeId).flatMap((group) => group.fields);
}

/** The unit's words beside an input; base money is the portfolio's currency. */
export function unitSuffix(unit: string | null, base: string, currency = base): string {
  if (!unit) return '';
  if (unit === 'base_money') return `млн ${currencySign(base)}`;
  if (unit === 'instrument_price') return `${currencySign(currency)}/шт.`;
  if (unit === 'fx_quote') return `${base}/${currency}`;
  if (unit === 'ratio') return 'коэф.';
  const money = /^([A-Z]{3})_million$/.exec(unit);
  if (money) return `млн ${currencySign(money[1])}`;
  return (
    {
      fraction: '%',
      days: 'дн.',
      months: 'мес.',
      years: 'лет',
      count: 'шт.',
      shares: 'шт.',
      percentage_point: 'п.п.',
      basis_point: 'б.п.',
    }[unit] ?? ''
  );
}

/** Percent on screen, fraction on the wire. */
export function toScreen(unit: string | null, value: number): number {
  return unit === 'fraction' ? Math.round(value * 1e6) / 1e4 : value;
}

export function fromScreen(unit: string | null, value: number): number {
  return unit === 'fraction' ? value / 100 : value;
}

export function allowsNegative(field: EditorField): boolean {
  if (['fraction', 'days', 'months', 'count', 'shares'].includes(field.unit ?? '')) return false;
  return field.minimum == null || field.minimum < 0;
}

function empty(value: unknown): boolean {
  return value == null || value === '' || (Array.isArray(value) && value.length === 0);
}

export function missingFields(position: DraftPosition): EditorField[] {
  return fieldsOf(position.instrument_type).filter(
    (field) => field.required && field.kind !== 'table' && empty(fieldValue(field, position)),
  );
}

export function derivedValue(field: EditorField, position: DraftPosition): string | undefined {
  const source = field.derive_from ? String(position[field.derive_from as keyof DraftPosition] ?? '').replaceAll('.', '') : '';
  if (!source) return undefined;
  return [...(field.derived_values ?? [])]
    .sort(([a], [b]) => b.replaceAll('.', '').length - a.replaceAll('.', '').length)
    .find(([prefix]) => source.startsWith(prefix.replaceAll('.', '')))?.[1];
}

export function fieldValue(field: EditorField, position: DraftPosition): unknown {
  const value = position.values[field.name];
  return empty(value) ? derivedValue(field, position) ?? field.default : value;
}

export function fieldHelp(field: EditorField, base: string, currency = base): string {
  const parts = [field.hint];
  const unit = unitSuffix(field.unit, base, currency);
  if (field.unit === 'fraction') parts.push('Введите процент: например, 15 для 15%.');
  else if (unit) parts.push(`Единицы ввода: ${unit}.`);
  if (field.kind === 'dates') parts.push('Даты через запятую в формате ГГГГ-ММ-ДД.');
  if (field.default != null && !field.derive_from) {
    const value = typeof field.default === 'number' ? toScreen(field.unit, field.default) : field.default;
    parts.push(`Если поле пусто, применяется ${String(value)}${unit ? ` ${unit}` : ''}.`);
  }
  if (!field.hint) {
    parts.unshift(field.target === 'position' ? 'Параметр вашей позиции в портфеле.'
      : field.target.startsWith('snapshot:') ? 'Укажите значение на дату оценки из отчётности или вашей оценки.'
        : 'Укажите значение из условий инструмента.');
  }
  return parts.filter(Boolean).join(' ');
}

/**
 * Quarter ends inside the next twelve full months, the calculation horizon: default test
 * dates of a new covenant row.
 */
export function quarterEnds(from = new Date()): string[] {
  const dates: string[] = [];
  for (let month = from.getMonth() + 1; month <= from.getMonth() + 12; month += 1) {
    if (month % 3 !== 2) continue; // March, June, September, December.
    dates.push(new Date(Date.UTC(from.getFullYear(), month + 1, 0)).toISOString().slice(0, 10));
  }
  return dates;
}

/** A new row of a table field: enum columns take their first option, dates the quarter ends. */
export function newRow(field: EditorField): Record<string, unknown> {
  return Object.fromEntries(
    field.columns.map((column) => [
      column.name,
      column.kind === 'enum' ? (column.options[0]?.[0] ?? '') : column.kind === 'dates' ? quarterEnds() : null,
    ]),
  );
}

export function emptyPosition(index: number, base: string): DraftPosition {
  return {
    position_id: `P${index}`,
    name: '',
    instrument_type: instrumentTypes()[0]?.asset_type ?? '',
    okved: '',
    currency: base,
    values: {},
    tables: {},
  };
}

/** Another type reads other inputs: keep only what it declares. */
export function retype(position: DraftPosition, typeId: string): DraftPosition {
  const declared = new Set(fieldsOf(typeId).map((f) => f.name));
  return {
    ...position,
    instrument_type: typeId,
    values: Object.fromEntries(Object.entries(position.values).filter(([name]) => declared.has(name))),
    tables: Object.fromEntries(Object.entries(position.tables).filter(([name]) => declared.has(name))),
  };
}

interface SnapshotItem {
  kind: string;
  subject: string;
  observed_on: string;
  values: Record<string, { value: number }>;
}

function plain(value: unknown): unknown {
  if (value && typeof value === 'object' && !Array.isArray(value) && 'value' in (value as object)) {
    return (value as { value: unknown }).value;
  }
  return value;
}

/**
 * An existing portfolio as an editable draft: terms and parameters by the fields' names, data
 * of the snapshot from the item of the field's kind about the instrument or its issuer (its
 * value by the field's name, or its only value). Numbers are kept; on save they are
 * re-attributed to the analyst as assumptions.
 */
export function draftFrom(name: string, bundle: PortfolioBundle, items: SnapshotItem[]): PortfolioDraft {
  const instruments = Object.fromEntries(bundle.instruments.map((i) => [i.instrument_id, i]));
  const parties = Object.fromEntries(bundle.parties.map((p) => [p.party_id, p]));
  const latest = (kind: string, subjects: string[]) =>
    items
      .filter((item) => item.kind === kind && subjects.includes(item.subject))
      .sort((a, b) => b.observed_on.localeCompare(a.observed_on))[0];
  return {
    name,
    base_currency: bundle.portfolio.base_currency,
    positions: bundle.positions.map((position) => {
      const instrument = instruments[position.instrument_id];
      const issuer = instrument?.issuer_id ? parties[instrument.issuer_id] : undefined;
      const values: Record<string, unknown> = {};
      const tables: Record<string, Record<string, unknown>[]> = {};
      for (const field of fieldsOf(instrument?.instrument_type ?? '')) {
        if (field.kind === 'table') {
          const rows = instrument?.terms[field.name];
          if (Array.isArray(rows)) {
            tables[field.name] = rows.map((row) =>
              Object.fromEntries(field.columns.map((c) => [c.name, plain((row as Record<string, unknown>)[c.name])])),
            );
          }
          continue;
        }
        let value: unknown;
        if (field.target === 'terms') value = plain(instrument?.terms[field.name]);
        else if (field.target === 'position') value = plain(position.params[field.name]);
        else if (field.target.startsWith('snapshot:')) {
          const item = latest(field.target.slice('snapshot:'.length), [position.instrument_id, instrument?.issuer_id ?? '']);
          const entries = Object.entries(item?.values ?? {});
          value = item?.values[field.name]?.value ?? (entries.length === 1 ? entries[0][1].value : undefined);
        }
        if (value != null) values[field.name] = value;
      }
      return {
        position_id: position.position_id,
        name: issuer?.name ?? instrument?.name ?? position.position_id,
        instrument_type: instrument?.instrument_type ?? '',
        okved: issuer?.okved ?? '',
        currency: instrument?.currency ?? bundle.portfolio.base_currency,
        values,
        tables,
      };
    }),
  };
}
