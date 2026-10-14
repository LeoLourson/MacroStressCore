import { ActionIcon, Alert, Anchor, Collapse, Drawer, Group, List, Stack, Table, Text, Title, Tooltip } from '@mantine/core';
import { useHotkeys } from '@mantine/hooks';
import { IconAlertTriangle, IconChevronDown, IconChevronUp, IconInfoCircle } from '@tabler/icons-react';
import { useEffect, useRef, useState } from 'react';
import { flagKind, metricLabel, modelLabel, viewFor, type ResultView } from '../../../api/catalog';
import type { Artifacts, CalculationResult, PositionContext } from '../../../api/types';
import { IntervalBar } from '../../../components/Interval';
import { ExecutionBadge, statusReasons } from '../../../components/RiskModel';
import { MetricCell, Section, StandardView } from '../../../components/ResultBlocks';
import { positionName, typeName } from '../../../lib/format';
import { DATA_QUALITY, flagList, flagOne, label } from '../../../lib/labels';
import type { Entries } from '../../../lib/provenance';
import { baselineOf, viewComponent } from '../../../plugins';
import type { Column } from './PositionsTab';

/** A position whose plugin declares no view is shown with all its metrics and sources. */
function fallbackView(result: CalculationResult): ResultView {
  return {
    view_id: 'standard',
    instrument_types: [result.instrument_type],
    component: null,
    blocks: [
      { kind: 'metrics', title: 'Показатели', metric_ids: [], path: '', columns: [], hint: '' },
      { kind: 'sources', title: 'Источники данных', metric_ids: [], path: '', columns: [], hint: '' },
    ],
    summary_metrics: [],
    labels: {},
  };
}

/** The metrics of the position's row in the list, each on the scale of its column. */
function KeyMetrics({ result, columns, entries }: { result: CalculationResult; columns: Column[]; entries: Entries }) {
  const shown = columns.filter((c) => result.metrics[c.metric]);
  if (!shown.length) return null;
  return (
    <Section title="Ключевые показатели" hint="Те же, что в списке позиций; полоса — на общей шкале столбца, рядом с остальными позициями.">
      <Table withTableBorder>
        <Table.Tbody>
          {shown.map((column) => {
            const metric = result.metrics[column.metric];
            const base = baselineOf(result, column.metric);
            const q = metric.quantiles;
            return (
              <Table.Tr key={column.metric}>
                <Table.Td>
                  <Text size="sm">{metricLabel(column.metric)}</Text>
                </Table.Td>
                <Table.Td className="num-right">
                  <MetricCell metric={metric} result={result} entries={entries} base={base} />
                </Table.Td>
                <Table.Td w={180}>
                  {q &&
                    (base != null ? (
                      <IntervalBar base={base} p05={base + q.p05} p50={base + q.p50} p95={base + q.p95} scale={column.levelScale} width="100%" />
                    ) : (
                      <IntervalBar p05={q.p05} p50={q.p50} p95={q.p95} scale={column.scale} width="100%" />
                    ))}
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Section>
  );
}

/**
 * Everything calculated for one position, opened in place from its row. The platform frames
 * it the same for every type: the position, its status and why, what limits the reading, the
 * row's metrics on the list's scale; the plugin's view in the middle; the method at the end.
 */
export function PositionDrawer({
  result,
  context,
  artifacts,
  shocks,
  entries,
  columns,
  order,
  onStep,
  onClose,
}: {
  result: CalculationResult | null;
  context: PositionContext | undefined;
  artifacts: Artifacts;
  shocks: Record<string, string>;
  entries: Entries;
  /** The columns of the position's table in the list. */
  columns: Column[];
  /** The positions in the order of the list: the panel steps through them. */
  order: string[];
  onStep: (positionId: string) => void;
  onClose: () => void;
}) {
  const [method, setMethod] = useState(false);
  const top = useRef<HTMLDivElement>(null);
  const names = artifacts.position_names;
  const at = result ? order.indexOf(result.position_id) : -1;
  const step = (by: number) => {
    const next = order[at + by];
    if (result && at >= 0 && next) onStep(next);
  };
  useHotkeys([
    ['alt+ArrowUp', () => step(-1)],
    ['alt+ArrowDown', () => step(1)],
  ]);
  // Another position opens at its top.
  useEffect(() => {
    top.current?.closest('.mantine-Drawer-content')?.scrollTo({ top: 0 });
  }, [result?.position_id]);

  const view = result ? (viewFor(result.instrument_type) ?? fallbackView(result)) : null;
  // A UI plugin's view when one is installed; otherwise the blocks the plugin declares.
  const View = (view && viewComponent(view.component)) ?? StandardView;
  const flags = result?.flags ?? [];
  const limits = flagList(flags.filter((f) => flagKind(f) === 'limit'), shocks);
  const methods = flagList(flags.filter((f) => flagKind(f) === 'informational'), shocks);
  const blocking = result?.diagnostics.filter((d) => d.severity === 'error') ?? [];
  const warnings = result?.diagnostics.filter((d) => d.severity === 'warning') ?? [];
  const important = [...new Set([...(result ? statusReasons(result, shocks) : []), ...warnings.map((d) => d.message || d.code), ...limits])];
  const meta = result
    ? [
        typeName(result.instrument_type),
        context?.instrument.currency,
        context?.issuer?.okved ? `ОКВЭД ${context.issuer.okved}` : null,
        `модель «${modelLabel(result.instrument_type, result.model_id)}», версия ${result.model_version}`,
        `качество данных ${label(DATA_QUALITY, result.data_quality.level)}`,
      ].filter(Boolean)
    : [];

  return (
    <Drawer
      opened={!!result}
      onClose={onClose}
      position="right"
      size="xl"
      styles={{ title: { flex: 1, minWidth: 0 } }}
      title={
        result && (
          <Group justify="space-between" wrap="nowrap" align="flex-start" gap="md">
            <Stack gap={0} style={{ minWidth: 0 }}>
              <Group gap="sm" wrap="nowrap" align="center">
                <Title order={4}>{positionName(result.position_id, names)}</Title>
                <ExecutionBadge result={result} />
              </Group>
              <Text size="xs" c="dimmed" ff="monospace">
                {result.position_id}
              </Text>
            </Stack>
            {at >= 0 && order.length > 1 && (
              <Group gap={4} wrap="nowrap">
                <Text size="xs" c="dimmed" className="nowrap">
                  {at + 1} из {order.length}
                </Text>
                <Tooltip label="Предыдущая позиция (Alt+↑)">
                  <ActionIcon variant="subtle" color="gray" disabled={at === 0} onClick={() => step(-1)} aria-label="Предыдущая позиция">
                    <IconChevronUp size={18} />
                  </ActionIcon>
                </Tooltip>
                <Tooltip label="Следующая позиция (Alt+↓)">
                  <ActionIcon
                    variant="subtle"
                    color="gray"
                    disabled={at === order.length - 1}
                    onClick={() => step(1)}
                    aria-label="Следующая позиция"
                  >
                    <IconChevronDown size={18} />
                  </ActionIcon>
                </Tooltip>
              </Group>
            )}
          </Group>
        )
      }
    >
      {result && view && (
        <Stack gap="lg" ref={top}>
          <Text size="sm" c="dimmed">
            {meta.join(' · ')}
          </Text>
          {result.execution === 'completed' && <KeyMetrics result={result} columns={columns} entries={entries} />}
          {result.execution !== 'completed' ? (
            <Alert color="gray" icon={<IconInfoCircle />} title="Позиция не рассчитана">
              <List size="sm" spacing={4}>
                {[...new Set([...blocking.map((d) => d.message || d.code), ...flags.map((f) => flagOne(f, shocks))])].map((line) => (
                  <List.Item key={line}>{line}</List.Item>
                ))}
              </List>
            </Alert>
          ) : (
            important.length > 0 && (
              <Alert color="orange" icon={<IconAlertTriangle />} title="Важно для чтения результата">
                <List size="sm" spacing={4}>
                  {important.map((line) => (
                    <List.Item key={line}>{line}</List.Item>
                  ))}
                </List>
              </Alert>
            )
          )}
          {result.execution === 'completed' && (
            <View result={result} context={context} view={view} artifacts={artifacts} entries={entries} shocks={shocks} />
          )}
          {(methods.length > 0 || result.limits?.note) && (
            <Stack gap={4}>
              {result.limits?.note && (
                <Text size="xs" c="dimmed">
                  Границы модели: {result.limits.note}
                </Text>
              )}
              {methods.length > 0 && (
                <>
                  <Anchor component="button" size="xs" w="fit-content" onClick={() => setMethod((v) => !v)} aria-expanded={method}>
                    {method ? 'Скрыть упрощения метода' : `Упрощения метода: ${methods.length}`}
                  </Anchor>
                  <Collapse in={method}>
                    <List size="xs" spacing={4} c="dimmed">
                      {methods.map((line) => (
                        <List.Item key={line}>{line}</List.Item>
                      ))}
                    </List>
                  </Collapse>
                </>
              )}
            </Stack>
          )}
        </Stack>
      )}
    </Drawer>
  );
}
