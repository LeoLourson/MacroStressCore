import { Code } from '@mantine/core';
import { Fragment, useMemo, type ReactNode } from 'react';
import type { Artifacts, NumberRef } from '../../api/types';
import { TracedNumber } from '../../components/Provenance';
import { lowerFirst } from '../../lib/format';
import { ACTIONS, AUTHORS, SOURCES, flagOne } from '../../lib/labels';
import { NumberMarker, type Entries } from '../../lib/provenance';
import { pluginGlosses } from '../../plugins';

// Section titles an advisory model may write as bare lines; the builder writes «### ».
const SECTIONS = new Set(['Резюме', 'Итог', 'Рекомендации', 'Допущения и авторы', 'Источники']);

const HEADING_GLOSS: Record<string, string> = {};

/**
 * Plain-language names for the machine identifiers a report may carry: actions, channels,
 * the plugins' own identifiers (UiPlugin.glosses), flags, sources and authors of the data
 * and the event document. They are
 * shown beside the identifier, never instead of it: the text itself is what gets signed.
 */
export function glossary(artifacts: Artifacts): Map<string, string> {
  const map = new Map<string, string>();
  for (const [code, name] of Object.entries(ACTIONS)) map.set(code, lowerFirst(name));
  for (const [code, name] of Object.entries({ ...SOURCES, ...AUTHORS })) map.set(code, name);
  for (const node of artifacts.graph?.nodes ?? []) {
    if (node.kind === 'channel') map.set(node.id, node.label);
  }
  for (const [code, name] of pluginGlosses(artifacts)) map.set(code, name);
  const doc = artifacts.document?.doc_id;
  if (doc) {
    map.set(doc, 'текст события');
    map.set(`#${doc}`, 'текст события');
  }
  return map;
}

const TOKEN = /#?[A-Za-z0-9](?:[A-Za-z0-9_.:-]*[A-Za-z0-9_])?/g;

function glossOf(token: string, names: Map<string, string>): string | null {
  const known = names.get(token);
  if (known) return known;
  const flag = flagOne(token);
  return flag !== token ? flag : null;
}

function glossed(text: string, names: Map<string, string>): ReactNode {
  const out: ReactNode[] = [];
  let at = 0;
  for (const match of text.matchAll(TOKEN)) {
    const gloss = glossOf(match[0], names);
    if (!gloss) continue;
    const end = match.index + match[0].length;
    out.push(text.slice(at, end), <span key={match.index} className="gloss"> ({gloss})</span>);
    at = end;
  }
  if (!out.length) return text;
  out.push(text.slice(at));
  return out;
}

const NO_NAMES = new Map<string, string>();

type Block = { kind: 'h' | 'p'; text: string } | { kind: 'ul'; items: string[] };

export function blocks(summary: string): Block[] {
  const out: Block[] = [];
  for (const raw of summary.split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    const heading = /^#{1,6}\s+(.*)$/.exec(line);
    const item = /^[-*•]\s+(.*)$/.exec(line);
    if (heading || SECTIONS.has(line)) {
      out.push({ kind: 'h', text: heading ? heading[1] : line });
    } else if (item) {
      const last = out[out.length - 1];
      if (last?.kind === 'ul') last.items.push(item[1]);
      else out.push({ kind: 'ul', items: [item[1]] });
    } else {
      out.push({ kind: 'p', text: line });
    }
  }
  return out;
}

type Run = { text: string; bold?: boolean; code?: boolean };

/** Inline Markdown the advisory model uses: **bold** and `code`. */
export function runs(text: string): Run[] {
  const out: Run[] = [];
  const pattern = /\*\*(.+?)\*\*|`([^`]+)`/g;
  let at = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > at) out.push({ text: text.slice(at, match.index) });
    out.push(match[1] !== undefined ? { text: match[1], bold: true } : { text: match[2], code: true });
    at = match.index + match[0].length;
  }
  if (at < text.length) out.push({ text: text.slice(at) });
  return out;
}

/** The report as it will be published; every number it is written with opens its origin. */
export function ReportText({
  summary,
  numbers,
  entries,
  names = NO_NAMES,
}: {
  summary: string;
  numbers: NumberRef[];
  entries: Entries;
  names?: Map<string, string>;
}) {
  const content = useMemo(() => {
    const marker = new NumberMarker(numbers, entries);
    const inline = (text: string): ReactNode =>
      runs(text).map((run, i) => {
        if (run.code) {
          const gloss = glossOf(run.text, names);
          return (
            <Fragment key={i}>
              <Code>{run.text}</Code>
              {gloss && <span className="gloss"> ({gloss})</span>}
            </Fragment>
          );
        }
        const marked = marker.mark(run.text).map((segment, j) =>
          segment.entry ? (
            <TracedNumber key={j} entry={segment.entry}>
              {segment.text}
            </TracedNumber>
          ) : (
            <Fragment key={j}>{glossed(segment.text, names)}</Fragment>
          ),
        );
        return run.bold ? <strong key={i}>{marked}</strong> : <Fragment key={i}>{marked}</Fragment>;
      });
    return blocks(summary).map((block, i) => {
      switch (block.kind) {
        case 'h':
          return (
            <h3 key={i}>
              {inline(block.text)}
              {HEADING_GLOSS[block.text] && <span className="gloss"> ({HEADING_GLOSS[block.text]})</span>}
            </h3>
          );
        case 'ul':
          return (
            <ul key={i}>
              {block.items.map((item, j) => (
                <li key={j}>{inline(item)}</li>
              ))}
            </ul>
          );
        default:
          return <p key={i}>{inline(block.text)}</p>;
      }
    });
  }, [summary, numbers, entries, names]);
  return <div className="prose">{content}</div>;
}
