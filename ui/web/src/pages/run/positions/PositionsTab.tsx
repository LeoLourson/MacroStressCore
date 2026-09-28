import { Badge, Group, Paper, Stack, Table, Text, Title, Tooltip } from '@mantine/core';
import { IconAlertTriangle, IconCheck } from '@tabler/icons-react';
import { useMemo, type ReactNode } from 'react';
import { useSearchParams } from 'react-router';
import { metricLabel, metricSpec, sliceSpec, viewFor } from '../../../api/catalog';
import type { CalculationResult, PortfolioResult, PositionContext } from '../../../api/types';
import { Interval, IntervalLegend, Shift, scaleOf } from '../../../components/Interval';
import { ExecutionBadge, ResultStatus } from '../../../components/RiskModel';
import { Term } from '../../../components/Term';
import { formatter, instrumentLine, positionName, positionTitle, typeName } from '../../../lib/format';
import { shockLabels, translateFlags } from '../../../lib/labels';
import { baselineOf } from '../../../plugins';
import type { RunTabProps } from '../RunPage';
import { useOrigins } from '../useOrigins';
import { PositionDrawer } from './PositionDrawer';

/**
 * What sets a position apart: not calculated, a result the model flags, or left out of a
 * slice's totals or admitted by a rule. A calculated and counted position shows nothing:
 * that is almost every row, and a column of the same mark tells nothing.
 */
function Exceptions({ result, portfolio }: { result: CalculationResult; portfolio: PortfolioResult | null | undefined }) {
  if (result.execution !== 'completed') {
    return (
      <Group mt={4}>
        <ExecutionBadge result={result} />
      </Group>
    );
  }
  const pieces: ReactNode[] = [];
  if (result.status !== 'ok') pieces.push(<ResultStatus key="status" status={result.status} />);
  if (!result.contributions.length) {
    pieces.push(
      <Text key="none" size="xs" c="dark.3">
        вне срезов
      </Text>,
    );
  }
  for (const c of result.contributions) {
    const slice = sliceSpec(c.slice_id)?.label ?? c.slice_id;
    const excluded = portfolio?.slices[c.slice_id]?.excluded.find((e) => e.position_id === result.position_id);
    if (excluded || c.admission.startsWith('excluded')) {
      pieces.push(
        <Tooltip key={c.slice_id} label={translateFlags(excluded?.reason ?? c.admission)} multiline maw={420}>
          <Badge color="orange" c="orange.9" variant="light" tt="none" fw={500} leftSection={<IconAlertTriangle size={12} />}>
            {slice}: не учтена
          </Badge>
        </Tooltip>,
      );
    } else if (c.admission.startsWith('admitted')) {
      pieces.push(
        <Group key={c.slice_id} gap={4} c="dark.3" wrap="nowrap">
          <IconCheck size={14} />
          <Text size="xs">{slice}: по правилу</Text>
        </Group>,
      );
    }
  }
  if (!pieces.length) return null;
  return (
    <Group gap="xs" mt={4}>
      {pieces}
    </Group>
  );
}

interface Group_ {
  type: string;
  results: CalculationResult[];
  metrics: string[];
}

function TypeTable({
  group,
  contexts,
  names,
  portfolio,
  onOpen,
}: {
  group: Group_;
  contexts: Record<string, PositionContext>;
  names: Record<string, string> | null | undefined;
  portfolio: PortfolioResult | null | undefined;
  onOpen: (id: string) => void;
}) {
  // One scale per column: the intervals of positions compare by eye. A change the plugin gives
  // the level before the event for is drawn as levels: before and after, from zero.
  const bases = Object.fromEntries(
    group.metrics.map((m) => [m, Object.fromEntries(group.results.map((r) => [r.position_id, baselineOf(r, m)]))]),
  );
  const scales = Object.fromEntries(
    group.metrics.map((m) => [
      m,
      scaleOf(group.results.flatMap((r) => [r.metrics[m]?.quantiles?.p05, r.metrics[m]?.quantiles?.p95])),
    ]),
  );
  const levelScales = Object.fromEntries(
    group.metrics.map((m) => [
      m,
      scaleOf(
        group.results.flatMap((r) => {
          const base = bases[m][r.position_id];
          const q = r.metrics[m]?.quantiles;
          return base != null && q ? [base, base + q.p05, base + q.p95] : [];
        }),
      ),
    ]),
  );
  // The worst first, by the first metric's own direction; not calculated last.
  const first = group.metrics[0];
  const sign = metricSpec(first)?.direction === 'lower_is_worse' ? 1 : -1;
  const key = (r: CalculationResult) => r.metrics[first]?.quantiles?.p50 ?? r.metrics[first]?.value;
  const rows = [...group.results].sort((a, b) => {
    const x = key(a);
    const y = key(b);
    if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;
    return sign * (x - y);
  });
  return (
    <Paper>
      <Table.ScrollContainer minWidth={330 + 280 * group.metrics.length}>
        <Table verticalSpacing="sm" horizontalSpacing="md" highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Позиция</Table.Th>
              {group.metrics.map((m) => (
                <Table.Th key={m} w={320} className="num-right">
                  {metricLabel(m)}
                </Table.Th>
              ))}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((r) => (
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
                    {r.position_id} · {instrumentLine(contexts[r.position_id])}
                  </Text>
                  <Exceptions result={r} portfolio={portfolio} />
                </Table.Td>
                {group.metrics.map((m) => {
                  const value = r.metrics[m];
                  const format = formatter(value?.unit ?? metricSpec(m)?.unit, metricSpec(m)?.decimals);
                  const base = bases[m][r.position_id];
                  return (
                    <Table.Td key={m}>
                      {value?.quantiles && base != null ? (
                        <Shift
                          base={base}
                          p05={value.quantiles.p05}
                          p50={value.quantiles.p50}
                          p95={value.quantiles.p95}
                          unit={value.unit}
                          scale={levelScales[m]}
                        />
                      ) : value?.quantiles ? (
                        <Interval
                          p05={value.quantiles.p05}
                          p50={value.quantiles.p50}
                          p95={value.quantiles.p95}
                          scale={scales[m]}
                          format={format}
                          width={110}
                        />
                      ) : value?.value != null ? (
                        <Text size="sm" ta="right" className="num">
                          {format(value.value)}
                        </Text>
                      ) : (
                        <Text size="sm" c="dimmed" ta="right">
                          не рассчитан
                        </Text>
                      )}
                    </Table.Td>
                  );
                })}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Paper>
  );
}

export function PositionsTab({ status, artifacts }: RunTabProps) {
  // The open position is in the address: a number's origin elsewhere can open it here.
  const [params, setParams] = useSearchParams();
  const chosen = params.get('position');
  const setChosen = (id: string | null) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (id) next.set('position', id);
        else next.delete('position');
        return next;
      },
      { replace: !id },
    );
  const { entries } = useOrigins(status);
  const results = useMemo(() => artifacts.results ?? [], [artifacts.results]);
  const contexts = useMemo(
    () => Object.fromEntries((artifacts.positions ?? []).map((c) => [c.position.position_id, c])),
    [artifacts.positions],
  );
  const names = artifacts.position_names;
  const shocks = shockLabels(artifacts.scenario?.parameters);
  const groups = useMemo(() => {
    const byType = new Map<string, CalculationResult[]>();
    for (const r of results) byType.set(r.instrument_type, [...(byType.get(r.instrument_type) ?? []), r]);
    return [...byType.entries()]
      .map(([type, items]): Group_ => {
        const declared = viewFor(type)?.summary_metrics ?? [];
        const present = declared.filter((m) => items.some((r) => r.metrics[m]));
        return { type, results: items, metrics: present.slice(0, 2) };
      })
      .sort((a, b) => typeName(a.type).localeCompare(typeName(b.type)));
  }, [results]);
  const untouched = Object.keys(contexts).filter((id) => !results.some((r) => r.position_id === id));
  const current = results.find((r) => r.position_id === chosen) ?? null;
  const shifts = groups.some((g) => g.metrics.some((m) => g.results.some((r) => r.metrics[m]?.quantiles && baselineOf(r, m) != null)));

  if (!results.length) {
    return <Text c="dimmed">Результаты по позициям появятся после расчёта.</Text>;
  }

  return (
    <Stack gap="lg">
      <Stack gap={6}>
        <Text size="sm" c="dark.3" maw={760}>
          {shifts
            ? 'Показатели роста — уровень до события → медиана после, ниже рост и его диапазон '
            : 'Медиана и диапазон '}
          <Term name="P5–P95">P5–P95</Term> по общим сценариям. Нажмите на строку, чтобы открыть разбор позиции.
        </Text>
        {shifts && <IntervalLegend base note="Шкала начинается с нуля и общая для столбца." />}
      </Stack>
      {groups.map((group) => (
        <Stack key={group.type} gap="xs">
          <Title order={5}>
            {typeName(group.type)} · {group.results.length}
          </Title>
          <TypeTable group={group} contexts={contexts} names={names} portfolio={artifacts.portfolio} onOpen={setChosen} />
        </Stack>
      ))}
      {untouched.length > 0 && (
        <Text size="sm" c="dark.3">
          Не затронуты событием: {untouched.sort().map((id) => positionTitle(id, names)).join(', ')}.
        </Text>
      )}
      <PositionDrawer
        result={current}
        context={current ? contexts[current.position_id] : undefined}
        artifacts={artifacts}
        shocks={shocks}
        entries={entries}
        onClose={() => setChosen(null)}
      />
    </Stack>
  );
}
