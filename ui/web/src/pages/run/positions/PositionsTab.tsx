import { Badge, Group, Paper, SegmentedControl, Stack, Table, Text, TextInput, Title, UnstyledButton } from '@mantine/core';
import { IconAlertTriangle, IconArrowDown, IconArrowUp, IconCheck, IconSearch, IconSelector } from '@tabler/icons-react';
import { useMemo, useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router';
import { metricLabel, metricSpec, sliceSpec, viewFor } from '../../../api/catalog';
import type { CalculationResult, PortfolioResult, PositionContext } from '../../../api/types';
import { Interval, IntervalLegend, Shift, scaleOf, type Scale } from '../../../components/Interval';
import { ExecutionBadge, ResultStatus, statusReasons } from '../../../components/RiskModel';
import { Term } from '../../../components/Term';
import { formatter, plural, positionName, positionTitle, typeName } from '../../../lib/format';
import { shockLabels, translateFlags } from '../../../lib/labels';
import { baselineOf } from '../../../plugins';
import type { RunTabProps } from '../RunPage';
import { useOrigins } from '../useOrigins';
import { PositionDrawer } from './PositionDrawer';

/** A summary metric of a table with its scales, shared by the table's positions. */
export interface Column {
  metric: string;
  /** The scale of the metric's interval. */
  scale: Scale;
  /** The scale of the levels before and after, for a change its plugin gives the level of. */
  levelScale: Scale;
}

/** The positions shown by one result view: the same summary metrics, one scale per column. */
interface Group_ {
  key: string;
  types: string[];
  results: CalculationResult[];
  columns: Column[];
}

/** By a column's metric, the worst first by its direction; or by name. `reverse` flips it. */
interface Sort {
  by: string | null;
  reverse: boolean;
}

type Filter = 'all' | 'attention' | 'not_run' | 'not_counted';

interface Mark {
  key: string;
  node: ReactNode;
}

function excludedFrom(result: CalculationResult, portfolio: PortfolioResult | null | undefined, sliceId: string) {
  return portfolio?.slices[sliceId]?.excluded.find((e) => e.position_id === result.position_id);
}

function notCounted(result: CalculationResult, portfolio: PortfolioResult | null | undefined): boolean {
  return (
    !result.contributions.length ||
    result.contributions.some((c) => c.admission.startsWith('excluded') || !!excludedFrom(result, portfolio, c.slice_id))
  );
}

function needsAttention(result: CalculationResult, portfolio: PortfolioResult | null | undefined): boolean {
  return result.execution !== 'completed' || result.status !== 'ok' || notCounted(result, portfolio);
}

/**
 * What sets a position apart: not calculated, a result the model flags (and why), or left out
 * of a slice's totals or admitted by a rule. A calculated and counted position has none.
 */
function marksOf(
  result: CalculationResult,
  portfolio: PortfolioResult | null | undefined,
  shocks: Record<string, string>,
): Mark[] {
  if (result.execution !== 'completed') return [{ key: `execution:${result.execution}`, node: <ExecutionBadge result={result} /> }];
  const marks: Mark[] = [];
  if (result.status !== 'ok') {
    const reasons = statusReasons(result, shocks);
    marks.push({
      key: `status:${result.status}:${reasons.join('|')}`,
      node: <ResultStatus status={result.status} reasons={reasons} size="xs" />,
    });
  }
  if (!result.contributions.length) {
    marks.push({
      key: 'no-slice',
      node: (
        <Text size="xs" c="dimmed">
          вне срезов
        </Text>
      ),
    });
  }
  for (const c of result.contributions) {
    const slice = sliceSpec(c.slice_id)?.label ?? c.slice_id;
    const excluded = excludedFrom(result, portfolio, c.slice_id);
    if (excluded || c.admission.startsWith('excluded')) {
      const reason = translateFlags(excluded?.reason ?? c.admission);
      marks.push({
        key: `excluded:${c.slice_id}:${reason}`,
        node: (
          <Group gap={4} wrap="nowrap" align="flex-start">
            <Badge color="orange" c="orange.9" leftSection={<IconAlertTriangle size={12} />}>
              {slice}: не учтена
            </Badge>
            <Text size="xs" c="dimmed">
              {reason}
            </Text>
          </Group>
        ),
      });
    } else if (c.admission.startsWith('admitted')) {
      marks.push({
        key: `admitted:${c.slice_id}`,
        node: (
          <Group gap={4} c="dimmed" wrap="nowrap">
            <IconCheck size={14} />
            <Text size="xs">{slice}: по правилу</Text>
          </Group>
        ),
      });
    }
  }
  return marks;
}

function sortRows(rows: CalculationResult[], sort: Sort, names: Record<string, string> | null | undefined): CalculationResult[] {
  if (!sort.by) {
    const sign = sort.reverse ? -1 : 1;
    return [...rows].sort((a, b) => sign * positionName(a.position_id, names).localeCompare(positionName(b.position_id, names)));
  }
  const metric = sort.by;
  // The worst first by the metric's own direction; not calculated last either way.
  const sign = (metricSpec(metric)?.direction === 'lower_is_worse' ? 1 : -1) * (sort.reverse ? -1 : 1);
  const key = (r: CalculationResult) => r.metrics[metric]?.quantiles?.p50 ?? r.metrics[metric]?.value;
  return [...rows].sort((a, b) => {
    const x = key(a);
    const y = key(b);
    if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;
    return sign * (x - y);
  });
}

/** The order of a column in words: a metric's worst first, a name from А to Я; or the reverse. */
function orderWords(metric: boolean, reverse: boolean): string {
  if (metric) return reverse ? 'сначала лучшие' : 'сначала худшие';
  return reverse ? 'от Я до А' : 'от А до Я';
}

/** How a sorted column is ordered, for assistive technology. */
function ariaSort(sort: Sort, by: string | null): 'ascending' | 'descending' | 'none' {
  if (sort.by !== by) return 'none';
  const ascending = by === null || metricSpec(by)?.direction === 'lower_is_worse';
  return ascending !== sort.reverse ? 'ascending' : 'descending';
}

function SortHeader({ label, by, sort, onSort }: { label: string; by: string | null; sort: Sort; onSort: (sort: Sort) => void }) {
  const active = sort.by === by;
  const Icon = !active ? IconSelector : sort.reverse ? IconArrowUp : IconArrowDown;
  const next = active ? { by, reverse: !sort.reverse } : { by, reverse: false };
  const now = active ? `, сейчас ${orderWords(by !== null, sort.reverse)}` : '';
  return (
    <UnstyledButton
      onClick={() => onSort(next)}
      aria-label={`${label}: упорядочить ${orderWords(by !== null, next.reverse)}${now}`}
      title={`Упорядочить ${orderWords(by !== null, next.reverse)}`}
      style={{ display: 'inline-flex', alignItems: 'center', gap: 4, font: 'inherit', fontWeight: 600 }}
    >
      {label}
      <Icon size={14} color={active ? undefined : 'var(--mantine-color-dark-2)'} />
    </UnstyledButton>
  );
}

function MetricValueCell({ result, column }: { result: CalculationResult; column: Column }) {
  const value = result.metrics[column.metric];
  const spec = metricSpec(column.metric);
  const format = formatter(value?.unit ?? spec?.unit, spec?.decimals);
  const base = baselineOf(result, column.metric);
  if (value?.quantiles && base != null) {
    const q = value.quantiles;
    return <Shift base={base} p05={q.p05} p50={q.p50} p95={q.p95} unit={value.unit} scale={column.levelScale} />;
  }
  if (value?.quantiles) {
    const q = value.quantiles;
    return <Interval p05={q.p05} p50={q.p50} p95={q.p95} scale={column.scale} format={format} width={110} />;
  }
  if (value?.value != null) {
    return (
      <Text size="sm" ta="right" className="num">
        {format(value.value)}
      </Text>
    );
  }
  return (
    <Text size="sm" c="dimmed" ta="right">
      не рассчитан
    </Text>
  );
}

function PositionTable({
  group,
  rows,
  sort,
  onSort,
  contexts,
  names,
  portfolio,
  shocks,
  onOpen,
}: {
  group: Group_;
  rows: CalculationResult[];
  sort: Sort;
  onSort: (sort: Sort) => void;
  contexts: Record<string, PositionContext>;
  names: Record<string, string> | null | undefined;
  portfolio: PortfolioResult | null | undefined;
  shocks: Record<string, string>;
  onOpen: (id: string) => void;
}) {
  const marks = Object.fromEntries(rows.map((r) => [r.position_id, marksOf(r, portfolio, shocks)]));
  // A mark every row carries tells nothing in a row: it is said once above the table.
  const common =
    rows.length > 1 ? (marks[rows[0].position_id] ?? []).filter((m) => rows.every((r) => marks[r.position_id].some((o) => o.key === m.key))) : [];
  const shared = new Set(common.map((m) => m.key));
  const several = group.types.length > 1;
  return (
    <Stack gap="xs">
      {common.length > 0 && (
        <Group gap="xs" align="flex-start" wrap="nowrap">
          <Text size="xs" c="dimmed" className="nowrap" mt={1}>
            У всех {plural(rows.length, 'позиции', 'позиций', 'позиций')}:
          </Text>
          <Stack gap={4}>
            {common.map((m) => (
              <div key={m.key}>{m.node}</div>
            ))}
          </Stack>
        </Group>
      )}
      <Paper>
        <Table.ScrollContainer minWidth={330 + 280 * group.columns.length}>
          <Table verticalSpacing="sm" horizontalSpacing="md" highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th aria-sort={ariaSort(sort, null)}>
                  <SortHeader label="Позиция" by={null} sort={sort} onSort={onSort} />
                </Table.Th>
                {group.columns.map(({ metric }) => (
                  <Table.Th key={metric} w={320} className="num-right" aria-sort={ariaSort(sort, metric)}>
                    <SortHeader label={metricLabel(metric)} by={metric} sort={sort} onSort={onSort} />
                  </Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((r) => {
                const context = contexts[r.position_id];
                const own = marks[r.position_id].filter((m) => !shared.has(m.key));
                const meta = [
                  several ? typeName(r.instrument_type) : null,
                  context?.instrument.currency,
                  context?.issuer?.okved ? `ОКВЭД ${context.issuer.okved}` : null,
                ].filter(Boolean);
                return (
                  <Table.Tr
                    key={r.position_id}
                    className="clickable-row"
                    tabIndex={0}
                    aria-label={`Разбор позиции ${positionName(r.position_id, names)}`}
                    onClick={() => onOpen(r.position_id)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        onOpen(r.position_id);
                      }
                    }}
                  >
                    <Table.Td>
                      <Text size="sm" fw={500}>
                        {positionName(r.position_id, names)}
                      </Text>
                      <Text size="xs" c="dimmed">
                        <Text span inherit ff="monospace">
                          {r.position_id}
                        </Text>
                        {meta.length > 0 && ` · ${meta.join(' · ')}`}
                      </Text>
                      {own.length > 0 && (
                        <Stack gap={4} mt={4}>
                          {own.map((m) => (
                            <div key={m.key}>{m.node}</div>
                          ))}
                        </Stack>
                      )}
                    </Table.Td>
                    {group.columns.map((column) => (
                      <Table.Td key={column.metric}>
                        <MetricValueCell result={r} column={column} />
                      </Table.Td>
                    ))}
                  </Table.Tr>
                );
              })}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Paper>
    </Stack>
  );
}

// Above this many positions the list gets a search field.
const SEARCH_FROM = 9;

export function PositionsTab({ status, artifacts }: RunTabProps) {
  // The open position is in the address: a number's origin elsewhere can open it here.
  const [params, setParams] = useSearchParams();
  const chosen = params.get('position');
  const setChosen = (id: string | null, replace = !id) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (id) next.set('position', id);
        else next.delete('position');
        return next;
      },
      { replace },
    );
  const [filter, setFilter] = useState<Filter>('all');
  const [query, setQuery] = useState('');
  const [sorts, setSorts] = useState<Record<string, Sort>>({});
  const { entries } = useOrigins(status);
  const results = useMemo(() => artifacts.results ?? [], [artifacts.results]);
  const contexts = useMemo(
    () => Object.fromEntries((artifacts.positions ?? []).map((c) => [c.position.position_id, c])),
    [artifacts.positions],
  );
  const names = artifacts.position_names;
  const portfolio = artifacts.portfolio;
  const shocks = useMemo(() => shockLabels(artifacts.scenario?.parameters), [artifacts.scenario?.parameters]);
  // One table per result view: positions a plugin shows by the same metrics are compared on
  // one scale, whatever their instrument types.
  const groups = useMemo(() => {
    const byView = new Map<string, CalculationResult[]>();
    for (const r of results) {
      const key = viewFor(r.instrument_type)?.view_id ?? `type:${r.instrument_type}`;
      byView.set(key, [...(byView.get(key) ?? []), r]);
    }
    return [...byView.entries()]
      .map(([key, items]): Group_ => {
        const declared = viewFor(items[0].instrument_type)?.summary_metrics ?? [];
        const metrics = declared.filter((m) => items.some((r) => r.metrics[m]));
        const types = [...new Set(items.map((r) => r.instrument_type))].sort((a, b) => typeName(a).localeCompare(typeName(b)));
        const columns = metrics.map((metric): Column => {
          const levels = items.flatMap((r) => {
            const base = baselineOf(r, metric);
            const q = r.metrics[metric]?.quantiles;
            return base != null && q ? [base, base + q.p05, base + q.p95] : [];
          });
          return {
            metric,
            scale: scaleOf(items.flatMap((r) => [r.metrics[metric]?.quantiles?.p05, r.metrics[metric]?.quantiles?.p95])),
            levelScale: scaleOf(levels),
          };
        });
        return { key, types, results: items, columns };
      })
      .sort((a, b) => typeName(a.types[0]).localeCompare(typeName(b.types[0])));
  }, [results]);

  const counts: Record<Filter, number> = {
    all: results.length,
    attention: results.filter((r) => needsAttention(r, portfolio)).length,
    not_run: results.filter((r) => r.execution !== 'completed').length,
    not_counted: results.filter((r) => notCounted(r, portfolio)).length,
  };
  const words: Record<Filter, string> = {
    all: 'Все',
    attention: 'Требуют внимания',
    not_run: 'Не рассчитаны',
    not_counted: 'Не учтены в итоге',
  };
  // A filter that keeps nothing or everything is not offered.
  const filters = (Object.keys(words) as Filter[]).filter((f) => f === 'all' || (counts[f] > 0 && counts[f] < results.length));
  const matches = (r: CalculationResult) => {
    if (filter === 'attention' && !needsAttention(r, portfolio)) return false;
    if (filter === 'not_run' && r.execution === 'completed') return false;
    if (filter === 'not_counted' && !notCounted(r, portfolio)) return false;
    const text = query.trim().toLowerCase();
    return !text || positionName(r.position_id, names).toLowerCase().includes(text) || r.position_id.toLowerCase().includes(text);
  };
  const sortOf = (group: Group_): Sort => sorts[group.key] ?? { by: group.columns[0]?.metric ?? null, reverse: false };
  const shown = groups
    .map((group) => ({ group, sort: sortOf(group), rows: sortRows(group.results.filter(matches), sortOf(group), names) }))
    .filter((item) => item.rows.length > 0);
  // The panel steps through the rows as listed; a position opened past the filter, through all.
  const visible = shown.flatMap((item) => item.rows.map((r) => r.position_id));
  const order =
    chosen && visible.includes(chosen)
      ? visible
      : groups.flatMap((group) => sortRows(group.results, sortOf(group), names).map((r) => r.position_id));

  const untouched = Object.keys(contexts).filter((id) => !results.some((r) => r.position_id === id));
  const current = results.find((r) => r.position_id === chosen) ?? null;
  const columns = current ? (groups.find((g) => g.results.includes(current))?.columns ?? []) : [];
  const levels = groups.some((g) => g.columns.some((c) => g.results.some((r) => r.metrics[c.metric]?.quantiles && baselineOf(r, c.metric) != null)));

  if (!results.length) {
    return <Text c="dimmed">Результаты по позициям появятся после расчёта.</Text>;
  }

  return (
    <Stack gap="lg">
      <Stack gap={4}>
        <Text size="sm" c="dimmed" maw={760}>
          {levels
            ? 'Показатели роста — уровень до события → медиана после, ниже рост и его диапазон '
            : 'Медиана и диапазон '}
          <Term name="P5–P95">P5–P95</Term> по общим сценариям. Нажмите на строку, чтобы открыть разбор позиции.
        </Text>
        {levels && <IntervalLegend base note="Шкала начинается с нуля и общая для столбца." />}
      </Stack>
      {(filters.length > 1 || results.length >= SEARCH_FROM) && (
        <Group gap="md">
          {filters.length > 1 && (
            <SegmentedControl
              size="xs"
              value={filter}
              onChange={(value) => setFilter(value as Filter)}
              data={filters.map((f) => ({ value: f, label: `${words[f]} · ${counts[f]}` }))}
            />
          )}
          {results.length >= SEARCH_FROM && (
            <TextInput
              size="xs"
              w={280}
              leftSection={<IconSearch size={14} />}
              placeholder="Название или идентификатор позиции"
              aria-label="Поиск позиции"
              value={query}
              onChange={(e) => setQuery(e.currentTarget.value)}
            />
          )}
        </Group>
      )}
      {shown.length === 0 && <Text className="empty">Нет позиций по этому условию.</Text>}
      {shown.map(({ group, sort, rows }) => (
        <Stack key={group.key} gap="xs">
          <Title order={5}>
            {group.types.map(typeName).join(', ')} · {rows.length < group.results.length ? `${rows.length} из ${group.results.length}` : rows.length}
          </Title>
          <PositionTable
            group={group}
            rows={rows}
            sort={sort}
            onSort={(next) => setSorts((prev) => ({ ...prev, [group.key]: next }))}
            contexts={contexts}
            names={names}
            portfolio={portfolio}
            shocks={shocks}
            onOpen={(id) => setChosen(id)}
          />
        </Stack>
      ))}
      {untouched.length > 0 && (
        <Text size="sm" c="dimmed">
          Не затронуты событием: {untouched.sort().map((id) => positionTitle(id, names)).join(', ')}.
        </Text>
      )}
      <PositionDrawer
        result={current}
        context={current ? contexts[current.position_id] : undefined}
        artifacts={artifacts}
        shocks={shocks}
        entries={entries}
        columns={columns}
        order={order}
        onStep={(id) => setChosen(id, true)}
        onClose={() => setChosen(null)}
      />
    </Stack>
  );
}
