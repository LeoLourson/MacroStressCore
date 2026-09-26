// The origin of every number the report is written with. The trace of a run is read once
// and joined to numbers on screen by metric_path. Ported from components/provenance.py.
import type { NumberRef, Trace, TraceNumber } from '../api/types';

export type Entries = Map<string, TraceNumber>;

export function entriesOf(trace: Trace | null | undefined): Entries {
  return new Map((trace?.numbers ?? []).map((n) => [n.metric_path, n]));
}

/** A mark is given only when the trace stands for the number actually shown. */
export function agrees(entry: TraceNumber, value: number | null | undefined): boolean {
  if (value == null) return true;
  return Math.abs(entry.value - value) < 0.5 * 10 ** -entry.number_ref.rounding;
}

/**
 * Round a decimal string half-to-even, like Python's Decimal.quantize: the report text is
 * written that way, and a number must be found by the same characters.
 */
export function roundHalfEven(value: number, digits: number): string {
  const text = expand(String(value));
  const negative = text.startsWith('-');
  const [whole, fraction = ''] = (negative ? text.slice(1) : text).split('.');
  if (fraction.length <= digits) {
    const padded = fraction.padEnd(digits, '0');
    return (negative ? '-' : '') + whole + (digits ? `.${padded}` : '');
  }
  const kept = whole + fraction.slice(0, digits);
  const rest = fraction.slice(digits);
  const last = Number(kept[kept.length - 1]);
  const up = rest[0] > '5' || (rest[0] === '5' && (/[1-9]/.test(rest.slice(1)) || last % 2 === 1));
  let digitsOut = kept;
  if (up) {
    const chars = kept.split('');
    let i = chars.length - 1;
    while (i >= 0) {
      if (chars[i] === '9') {
        chars[i] = '0';
        i -= 1;
      } else {
        chars[i] = String(Number(chars[i]) + 1);
        break;
      }
    }
    digitsOut = (i < 0 ? '1' : '') + chars.join('');
  }
  const cut = digitsOut.length - digits;
  const result = digits ? `${digitsOut.slice(0, cut)}.${digitsOut.slice(cut)}` : digitsOut;
  const zero = /^0*\.?0*$/.test(result);
  return (negative && !zero ? '-' : '') + result;
}

function expand(text: string): string {
  // 1e-7 → 0.0000001: exponent notation never appears in the report text.
  if (!/e/i.test(text)) return text;
  const [mantissa, exponent] = text.toLowerCase().split('e');
  const power = Number(exponent);
  const negative = mantissa.startsWith('-');
  const [whole, fraction = ''] = mantissa.replace('-', '').split('.');
  const digits = whole + fraction;
  const point = whole.length + power;
  const body =
    point <= 0
      ? `0.${'0'.repeat(-point)}${digits}`
      : point >= digits.length
        ? digits + '0'.repeat(point - digits.length)
        : `${digits.slice(0, point)}.${digits.slice(point)}`;
  return (negative ? '-' : '') + body;
}

export function printed(ref: NumberRef): string {
  return roundHalfEven(ref.value, ref.rounding);
}

export type Segment = { text: string; entry?: TraceNumber };

/**
 * Split report text into plain runs and numbers that carry their origin. The report writes
 * its numbers in the order of `numbers`, so they are looked for in that order.
 */
export class NumberMarker {
  private pending: TraceNumber[];

  constructor(numbers: NumberRef[], entries: Entries) {
    this.pending = numbers
      .map((ref) => entries.get(ref.metric_path))
      .filter((entry): entry is TraceNumber => !!entry);
  }

  mark(text: string): Segment[] {
    const out: Segment[] = [];
    let at = 0;
    while (this.pending.length) {
      // Reports are written with a decimal comma; earlier ones with a point.
      const point = printed(this.pending[0].number_ref);
      const found = [point, point.replace('.', ',')]
        .map((candidate) => [text.indexOf(candidate, at), candidate] as const)
        .filter(([index]) => index >= 0)
        .sort((a, b) => a[0] - b[0])[0];
      if (!found) break;
      const [index, token] = found;
      const entry = this.pending.shift()!;
      if (index > at) out.push({ text: text.slice(at, index) });
      out.push({ text: token, entry });
      at = index + token.length;
    }
    if (at < text.length) out.push({ text: text.slice(at) });
    return out;
  }
}
