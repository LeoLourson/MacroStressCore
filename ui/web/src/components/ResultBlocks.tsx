// The standard blocks of a position's result, and the standard view built from the blocks
// a plugin declares (ResultView.blocks). A UI plugin may use them in its own view.
import { Box, Group, List, Stack, Table, Text, Title } from '@mantine/core';
import type { ReactNode } from 'react';
import { metricLabel, metricSpec, type ViewBlock } from '../api/catalog';
import type { CalculationResult, Evidence, MetricValue } from '../api/types';
import { compact, day, formatter, metricValue, number, percent, positionPath, resolvePath } from '../lib/format';
import { basisText } from '../lib/origin';
import type { Entries } from '../lib/provenance';
import type { PositionViewProps } from '../plugins/sdk';
import { IntervalText } from './Interval';
import { TracedNumber } from './Provenance';
import { Term } from './Term';

export function Section({ title, hint, children }: { title: ReactNode; hint?: string; children: ReactNode }) {
  return (
    <Stack gap="xs">
      <Title order={5}>{title}</Title>
      {hint && (
        <Text size="xs" c="dark.3">
          {hint}
        </Text>
      )}
      {children}
    </Stack>
  );
}

export function Fact({ name, value }: { name: ReactNode; value: ReactNode }) {
  return (
    <Stack gap={0}>
      <Text size="xs" c="dark.3">
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

/** A metric as the screens show it: P50 with P5 … P95 beside it, or the value itself. */
export function MetricCell({
  metric,
  positionId,
  entries,
}: {
  metric: MetricValue;
  positionId: string;
  entries: Entries;
}) {
  const digits = metricSpec(metric.metric_id)?.decimals;
  const format = formatter(metric.unit, digits);
  const q = metric.quantiles;
  if (q) {
    return (
      <TracedNumber entry={entries.get(positionPath(positionId, 'metrics', metric.metric_id, 'p50'))}>
        <IntervalText p05={q.p05} p50={q.p50} p95={q.p95} format={format} />
      </TracedNumber>
    );
  }
  return (
    <TracedNumber entry={entries.get(positionPath(positionId, 'metrics', metric.metric_id, 'value'))}>
      <Text size="sm" fw={600} className="num">
        {format(metric.value)}
      </Text>
    </TracedNumber>
  );
}

export function MetricsBlock({
  result,
  metricIds,
  entries,
  title,
  hint,
}: {
  result: CalculationResult;
  metricIds: string[];
  entries: Entries;
  title: string;
  hint?: string;
}) {
  const shown = (metricIds.length ? metricIds : Object.keys(result.metrics)).filter((id) => result.metrics[id]);
  if (!shown.length) return null;
  return (
    <Section
      title={title}
      hint={hint || 'Распределения — медиана (P50) и диапазон P5 … P95 по общим сценариям; значения без диапазона детерминированы.'}
    >
      <Table withTableBorder fz="sm" verticalSpacing={6}>
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
                  <Text size="xs" c="dark.3">
                    {metricSpec(id)!.description}
                  </Text>
                )}
              </Table.Td>
              <Table.Td className="num-right">
                <MetricCell metric={result.metrics[id]} positionId={result.position_id} entries={entries} />
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
        <Table withTableBorder fz="sm" verticalSpacing={6}>
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

/** Counts of realisations by loss: the shape of the distribution, drawn as data. */
export function HistogramBlock({
  histogram,
  unit,
  title,
  hint,
}: {
  histogram: unknown;
  unit: string;
  title: string;
  hint?: string;
}) {
  const h = histogram as { edges?: number[]; counts?: number[] } | undefined;
  if (!h?.edges || !h.counts?.length) return null;
  const top = Math.max(...h.counts) || 1;
  const total = h.counts.reduce((a, b) => a + b, 0) || 1;
  const format = formatter(unit);
  return (
    <Section title={title} hint={hint || 'Доля сценариев по интервалам потерь; положительные — потери, отрицательные — прирост.'}>
      <Stack gap={2}>
        {h.counts.map((count, i) => (
          <Group key={i} gap="sm" wrap="nowrap">
            <Text size="xs" w={210} className="num-right" c="dark.4">
              {format(h.edges![i])} … {format(h.edges![i + 1])}
            </Text>
            <Box style={{ flex: 1 }} h={8} bg="gray.1">
              <Box h={8} bg="steel.4" w={`${(count / top) * 100}%`} />
            </Box>
            <Text size="xs" w={48} className="num-right">
              {percent(count / total, 1)}
            </Text>
          </Group>
        ))}
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
      <Table withTableBorder fz="sm" verticalSpacing={6}>
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

/** Who stands behind the position's data, grouped by basis. */
export function SourcesBlock({ result, title = 'Источники данных' }: { result: CalculationResult; title?: string }) {
  const grouped = new Map<string, Evidence[]>();
  for (const e of result.sources) grouped.set(basisText(e), [...(grouped.get(basisText(e)) ?? []), e]);
  const inputs = Object.entries(result.input_sources ?? {});
  if (!grouped.size && !inputs.length) return null;
  return (
    <Section title={title}>
      <List size="sm" spacing={2}>
        {[...grouped.entries()].map(([basis, items]) => (
          <List.Item key={basis}>
            {basis} — {items.length} {items.length === 1 ? 'значение' : 'значений'}
          </List.Item>
        ))}
      </List>
      {inputs.length > 0 && (
        <Text size="xs" c="dark.3">
          Данные снимка: {inputs.map(([key, ids]) => `${key} (${ids.join(', ') || 'без источника'})`).join('; ')}.
        </Text>
      )}
    </Section>
  );
}

/** The result rendered from the blocks its plugin declares: the view of any new plugin. */
export function StandardView({ result, view, entries }: PositionViewProps) {
  return (
    <Stack gap="lg">
      {view.blocks.map((block, i) => {
        const data = block.path ? resolvePath(result.details, block.path) : undefined;
        switch (block.kind) {
          case 'metric':
          case 'metrics':
            return <MetricsBlock key={i} result={result} metricIds={block.metric_ids} entries={entries} title={block.title} hint={block.hint} />;
          case 'text':
            return (
              <Section key={i} title={block.title}>
                <Text size="sm">{typeof data === 'string' ? data : block.hint}</Text>
              </Section>
            );
          case 'table':
            return <TableBlock key={i} rows={data} block={block} />;
          case 'histogram':
            return <HistogramBlock key={i} histogram={data} unit={`${result.base_currency}_million`} title={block.title} hint={block.hint} />;
          case 'series':
            return <SeriesBlock key={i} series={data} labels={view.labels} title={block.title} hint={block.hint} />;
          case 'sources':
            return <SourcesBlock key={i} result={result} title={block.title} />;
          default:
            return null;
        }
      })}
    </Stack>
  );
}
