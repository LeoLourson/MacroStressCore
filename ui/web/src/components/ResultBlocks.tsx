// The standard blocks of a position's result, and the standard view built from the blocks
// a plugin declares (ResultView.blocks). A UI plugin may use them in its own view.
import { Box, Group, Stack, Table, Text, Tooltip } from '@mantine/core';
import type { ReactNode } from 'react';
import { metricLabel, metricSpec, type ViewBlock } from '../api/catalog';
import type { CalculationResult, MetricValue, PositionContext, Quantiles, TraceNumber } from '../api/types';
import { change, compact, day, formatter, metricValue, number, percent, resolvePath } from '../lib/format';
import { metricOrigin } from '../lib/origin';
import type { Entries } from '../lib/provenance';
import { bySource, positionInputs } from '../lib/sources';
import type { PositionViewProps } from '../plugins/sdk';
import { IntervalText, ShiftText } from './Interval';
import { SourceInputs, TracedNumber } from './Provenance';
import { Subsection } from './Page';
import { Term } from './Term';

/** A block of a position's result: the group heading of the page, its hint pops up. */
export function Section({ title, hint, children }: { title: ReactNode; hint?: string; children: ReactNode }) {
  return (
    <Subsection title={title} hint={hint || undefined}>
      {children}
    </Subsection>
  );
}

export function Fact({ name, value }: { name: ReactNode; value: ReactNode }) {
  return (
    <Stack gap={0}>
      <Text size="xs" c="dimmed">
        {name}
      </Text>
      {typeof value === 'string' ? (
        <Text size="sm" fw={500} className="num">
          {value}
        </Text>
      ) : (
        value
      )}
    </Stack>
  );
}

/**
 * A metric as the screens show it: P50 with P5 … P95 beside it, or the value itself. A change
 * with the level it starts from (`base`) reads «before → after» with the change below. The
 * number opens its origin; the mean of the worst 5 % (ES95) is under it when the model gives it.
 */
export function MetricCell({
  metric,
  result,
  entries,
  base,
}: {
  metric: MetricValue;
  result: CalculationResult;
  entries: Entries;
  base?: number | null;
}) {
  const digits = metricSpec(metric.metric_id)?.decimals;
  const format = formatter(metric.unit, digits);
  const q = metric.quantiles;
  if (!q) {
    return (
      <TracedNumber entry={metricOrigin(entries, result, metric.metric_id, 'value')}>
        <Text size="sm" fw={600} className="num">
          {format(metric.value)}
        </Text>
      </TracedNumber>
    );
  }
  return (
    <Stack gap={0} align="flex-end">
      <TracedNumber entry={metricOrigin(entries, result, metric.metric_id, 'p50')}>
        {base != null ? (
          <ShiftText base={base} p05={q.p05} p50={q.p50} p95={q.p95} unit={metric.unit} />
        ) : (
          <IntervalText p05={q.p05} p50={q.p50} p95={q.p95} format={format} />
        )}
      </TracedNumber>
      {q.es95 != null && (
        <Text size="xs" c="dimmed" className="num">
          <Term name="ES95">ES95</Term>: {base != null ? change(q.es95, metric.unit) : format(q.es95)}
        </Text>
      )}
    </Stack>
  );
}

export function MetricsBlock({
  result,
  metricIds,
  entries,
  title,
  hint,
  baseline,
  exclude = [],
}: {
  result: CalculationResult;
  metricIds: string[];
  entries: Entries;
  title: string;
  hint?: string;
  /** The level before the event a change metric starts from (UiPlugin.baseline). */
  baseline?: (metricId: string) => number | null;
  /** Metrics shown elsewhere on the screen: the view's summary metrics, above the view. */
  exclude?: string[];
}) {
  const shown = (metricIds.length ? metricIds : Object.keys(result.metrics)).filter(
    (id) => result.metrics[id] && !exclude.includes(id),
  );
  if (!shown.length) return null;
  return (
    <Section
      title={title}
      hint={hint || 'Распределения — медиана (P50) и диапазон P5 … P95 по общим сценариям; значения без диапазона детерминированы.'}
    >
      <Table withTableBorder>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Показатель</Table.Th>
            <Table.Th className="num-right">
              <Term name="P5–P95">P50 · P5 … P95</Term>
            </Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {shown.map((id) => (
            <Table.Tr key={id}>
              <Table.Td>
                <Text size="sm">{metricLabel(id)}</Text>
                {metricSpec(id)?.description && (
                  <Text size="xs" c="dimmed">
                    {metricSpec(id)!.description}
                  </Text>
                )}
              </Table.Td>
              <Table.Td className="num-right">
                <MetricCell metric={result.metrics[id]} result={result} entries={entries} base={baseline?.(id)} />
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Section>
  );
}

/** A cell of a declared table: numbers by the column's name, the rest as text. */
function cellText(key: string, value: unknown): string {
  if (value == null) return '—';
  if (typeof value === 'number') {
    if (/probability|share/.test(key)) return percent(value, 0);
    return Math.abs(value) < 1 && value !== 0 ? compact(value) : number(value);
  }
  if (typeof value === 'boolean') return value ? 'да' : 'нет';
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)) return day(value);
  return String(value);
}

export function TableBlock({ rows, block }: { rows: unknown; block: ViewBlock }) {
  const items = Array.isArray(rows)
    ? (rows as Record<string, unknown>[])
    : rows && typeof rows === 'object'
      ? Object.values(rows as Record<string, Record<string, unknown>>)
      : [];
  if (!items.length) return null;
  const columns = block.columns.length ? block.columns : Object.keys(items[0]).map((k) => [k, k] as [string, string]);
  return (
    <Section title={block.title} hint={block.hint}>
      <Table.ScrollContainer minWidth={480}>
        <Table withTableBorder>
          <Table.Thead>
            <Table.Tr>
              {columns.map(([key, title]) => (
                <Table.Th key={key}>{title}</Table.Th>
              ))}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {items.map((row, i) => (
              <Table.Tr key={i}>
                {columns.map(([key]) => (
                  <Table.Td key={key} className={typeof row[key] === 'number' ? 'num-right' : undefined}>
                    {cellText(key, row[key])}
                  </Table.Td>
                ))}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Section>
  );
}

// Bins at the ends with fewer scenarios than this only stretch the axis.
const EMPTY_BIN = 0.0005;

const MEDIAN_LINE = '3px solid var(--mantine-color-steel-8)';
const TAIL_LINE = '2px dashed var(--mantine-color-dark-3)';

/**
 * Counts of realisations by loss: the shape of the distribution, drawn as data. With the
 * metric's `quantiles` its P5, median and P95 are marked on the same axis.
 */
export function HistogramBlock({
  histogram,
  unit,
  title,
  hint,
  quantiles,
}: {
  histogram: unknown;
  unit: string;
  title: string;
  hint?: string;
  quantiles?: Quantiles | null;
}) {
  const h = histogram as { edges?: number[]; counts?: number[] } | undefined;
  if (!h?.edges || !h.counts?.length) return null;
  const counts = h.counts;
  const edges = h.edges;
  const total = counts.reduce((a, b) => a + b, 0) || 1;
  let first = 0;
  let last = counts.length - 1;
  while (first < last && counts[first] / total < EMPTY_BIN) first += 1;
  while (last > first && counts[last] / total < EMPTY_BIN) last -= 1;
  const bins = counts.slice(first, last + 1);
  const lo = edges[first];
  const hi = edges[last + 1];
  const top = Math.max(...bins) || 1;
  const format = formatter(unit);
  const at = (value: number) => Math.min(100, Math.max(0, ((value - lo) / (hi - lo || 1)) * 100));
  const marks = quantiles
    ? [
        { name: 'P5', value: quantiles.p05, line: TAIL_LINE },
        { name: 'медиана', value: quantiles.p50, line: MEDIAN_LINE },
        { name: 'P95', value: quantiles.p95, line: TAIL_LINE },
      ]
    : [];
  return (
    <Section title={title} hint={hint || 'Доля сценариев по интервалам потерь; положительные — потери, отрицательные — прирост.'}>
      <Stack gap={4}>
        <Box
          pos="relative"
          h={96}
          role="img"
          aria-label={`Распределение от ${format(lo)} до ${format(hi)}${marks.map((m) => `, ${m.name} ${format(m.value)}`).join('')}`}
        >
          <Group gap={1} align="flex-end" h="100%" wrap="nowrap">
            {bins.map((count, i) => (
              <Tooltip key={i} label={`${format(edges[first + i])} … ${format(edges[first + i + 1])}: ${percent(count / total, 1)} сценариев`}>
                <Box
                  style={{ flex: 1, borderRadius: '2px 2px 0 0' }}
                  h={`${count ? Math.max((count / top) * 100, 2) : 0}%`}
                  bg="steel.2"
                />
              </Tooltip>
            ))}
          </Group>
          {lo < 0 && hi > 0 && <Box pos="absolute" top={0} bottom={0} w={1} bg="gray.5" style={{ left: `${at(0)}%` }} />}
          {marks.map((m) => (
            <Box key={m.name} pos="absolute" top={0} bottom={0} style={{ left: `calc(${at(m.value)}% - 1px)`, borderLeft: m.line }} />
          ))}
        </Box>
        <Group justify="space-between" gap="xs">
          <Text size="xs" c="dimmed" className="num">
            {format(lo)}
          </Text>
          <Text size="xs" c="dimmed" className="num">
            {format(hi)}
          </Text>
        </Group>
        {marks.length > 0 && (
          <Group gap="md" style={{ rowGap: 4 }}>
            {marks.map((m) => (
              <Group key={m.name} gap={4} wrap="nowrap">
                <Box h={12} style={{ borderLeft: m.line }} />
                <Text size="xs" c="dimmed" className="num">
                  {m.name} {format(m.value)}
                </Text>
              </Group>
            ))}
          </Group>
        )}
      </Stack>
    </Section>
  );
}

export interface Contribution {
  key: string;
  label: string;
  value: number;
}

// A plus only before a change that shows in the digits.
function signed(text: string, value: number): string {
  return value > 0 && /[1-9]/.test(text) ? `+${text}` : text;
}

/**
 * The parts of a result by channel or factor (Shapley values), the largest first. Which way a
 * part pushes follows the metric's direction: towards the worse — in colour and in words. The
 * parts that are zero are named in one line: what the event did not move is worth knowing.
 */
export function ContributionsBlock({
  items,
  metricId,
  format,
  title,
  hint,
  origin,
}: {
  items: Contribution[];
  /** The metric the parts add up to: its direction says which sign is worse. */
  metricId: string;
  format: (value: number) => string;
  title: ReactNode;
  hint?: string;
  /** The origin of a part, by its key, when the report cites it. */
  origin?: (key: string) => TraceNumber | undefined;
}) {
  const moved = items.filter((i) => /[1-9]/.test(format(i.value))).sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
  const still = items.filter((i) => !moved.includes(i));
  if (!moved.length) return null;
  const lowerIsWorse = metricSpec(metricId)?.direction === 'lower_is_worse';
  const worse = (value: number) => (lowerIsWorse ? value < 0 : value > 0);
  const top = Math.max(...moved.map((i) => Math.abs(i.value))) || 1;
  return (
    <Section title={title} hint={hint}>
      <Stack gap={4}>
        {moved.map((item) => (
          <Group key={item.key} gap="sm" wrap="nowrap">
            <Text size="sm" w={220} lineClamp={2}>
              {item.label}
            </Text>
            <Box style={{ flex: 1 }} h={10} bg="gray.1">
              <Box h={10} bg={worse(item.value) ? 'steel.6' : 'gray.4'} w={`${(Math.abs(item.value) / top) * 100}%`} />
            </Box>
            <Text size="sm" w={130} className="num-right">
              <TracedNumber entry={origin?.(item.key)}>{signed(format(item.value), item.value)}</TracedNumber>
            </Text>
            <Text size="xs" w={70} c="dimmed">
              {worse(item.value) ? 'ухудшает' : 'улучшает'}
            </Text>
          </Group>
        ))}
        {still.length > 0 && (
          <Text size="xs" c="dimmed">
            Не повлияли: {still.map((i) => i.label).join(', ')}.
          </Text>
        )}
      </Stack>
    </Section>
  );
}

interface Series {
  name?: string;
  unit: string;
  values: (number | null)[];
}

/** Monthly series at the horizon's end; a plugin may draw them in its own view. */
export function SeriesBlock({
  series,
  labels,
  title,
  hint,
}: {
  series: unknown;
  labels: Record<string, string>;
  title: string;
  hint?: string;
}) {
  const entries = Object.entries((series ?? {}) as Record<string, Series>).filter(([, s]) => Array.isArray(s?.values));
  if (!entries.length) return null;
  return (
    <Section title={title} hint={hint}>
      <Table withTableBorder>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Показатель</Table.Th>
            <Table.Th className="num-right">Первый месяц</Table.Th>
            <Table.Th className="num-right">Конец горизонта</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {entries.map(([name, s]) => (
            <Table.Tr key={name}>
              <Table.Td>{labels[name] ?? name}</Table.Td>
              <Table.Td className="num-right">{metricValue(s.values[0], s.unit)}</Table.Td>
              <Table.Td className="num-right">{metricValue(s.values[s.values.length - 1], s.unit)}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Section>
  );
}

/** Where the position's data came from: each source, whose and on what date, and what it gave. */
export function SourcesBlock({
  result,
  context,
  title = 'Источники данных',
}: {
  result: CalculationResult;
  context?: PositionContext;
  title?: string;
}) {
  const sources = bySource(positionInputs(context, result));
  if (!sources.length) return null;
  return (
    <Section title={title}>
      <Stack gap="sm">
        {sources.map((source) => (
          <Stack key={source.key} gap={4}>
            <Text size="sm" fw={600}>
              {source.name}
            </Text>
            <SourceInputs source={source} />
          </Stack>
        ))}
      </Stack>
    </Section>
  );
}

/**
 * The result rendered from the blocks its plugin declares: the view of any new plugin. The
 * summary metrics are above the view, in the panel's own block, and are not repeated.
 */
export function StandardView({ result, context, view, entries }: PositionViewProps) {
  return (
    <Stack gap="lg">
      {view.blocks.map((block, i) => {
        const data = block.path ? resolvePath(result.details, block.path) : undefined;
        switch (block.kind) {
          case 'metric':
          case 'metrics':
            return (
              <MetricsBlock
                key={i}
                result={result}
                metricIds={block.metric_ids}
                entries={entries}
                title={block.title}
                hint={block.hint}
                exclude={view.summary_metrics}
              />
            );
          case 'text':
            return (
              <Section key={i} title={block.title}>
                <Text size="sm">{typeof data === 'string' ? data : block.hint}</Text>
              </Section>
            );
          case 'table':
            return <TableBlock key={i} rows={data} block={block} />;
          case 'histogram':
            return (
              <HistogramBlock
                key={i}
                histogram={data}
                unit={`${result.base_currency}_million`}
                title={block.title}
                hint={block.hint}
                quantiles={block.metric_ids[0] ? result.metrics[block.metric_ids[0]]?.quantiles : null}
              />
            );
          case 'series':
            return <SeriesBlock key={i} series={data} labels={view.labels} title={block.title} hint={block.hint} />;
          case 'sources':
            return <SourcesBlock key={i} result={result} context={context} title={block.title} />;
          default:
            return null;
        }
      })}
    </Stack>
  );
}
