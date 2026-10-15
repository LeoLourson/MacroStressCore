import { Group, Stack, Text } from '@mantine/core';
import type { ReactNode } from 'react';
import { sliceSpec } from '../api/catalog';
import type { Artifacts, SliceResult } from '../api/types';
import { formatter, slicePath } from '../lib/format';
import type { Entries } from '../lib/provenance';
import { baselineOf } from '../plugins';
import { IntervalBar, IntervalLegend, scaleOf } from './Interval';
import { TracedNumber } from './Provenance';
import { Term } from './Term';

/** The level before the event: the sum of the included positions' levels, when each is known. */
export function sliceBase(item: SliceResult, artifacts: Artifacts): number | null {
  const levels = item.included.map((id) => {
    const result = artifacts.results?.find((r) => r.position_id === id);
    return result ? baselineOf(result, item.measure) : null;
  });
  return levels.length && levels.every((v) => v != null) ? levels.reduce((a: number, v) => a + v!, 0) : null;
}

/** The headline of a slice: P50 large, P5 and P95 beside it, the bar on one scale; every number opens its origin. */
export function ResultSummary({
  item,
  entries,
  conclusion,
}: {
  item: SliceResult;
  /** Kept for the callers; the headline draws the change alone. */
  artifacts?: Artifacts;
  entries: Entries;
  conclusion?: ReactNode;
}) {
  const q = item.loss_quantiles;
  if (!q) return null;
  const spec = sliceSpec(item.slice_id);
  const format = formatter(item.unit);
  const es = item.expected_shortfall_95;
  // The bar draws what the numbers above it say: the change, from zero. The level before the
  // event would take most of the width and leave the interval a sliver at its end.
  const scale = scaleOf([q.p05, q.p95, item.sum_of_individual_p95, es]);
  const traced = (key: string, value: number) => (
    <TracedNumber entry={entries.get(slicePath(item.slice_id, 'loss_quantiles', key))}>{format(value)}</TracedNumber>
  );
  return (
    <Stack gap="xs">
      {conclusion && (
        <Text size="md" maw="80ch">
          {conclusion}
        </Text>
      )}
      <Group gap="xl" align="flex-end">
        <Stack gap={0}>
          <Text size="xs" c="dimmed">
            {spec?.measure_label ?? 'Потери'}, медиана (P50)
          </Text>
          <Text fz="xl" fw={600} className="num" lh={1.2}>
            {traced('p50', q.p50)}
          </Text>
        </Stack>
        <Stack gap={0}>
          <Text size="xs" c="dimmed">
            P5
          </Text>
          <Text size="lg" className="num">
            {traced('p05', q.p05)}
          </Text>
        </Stack>
        <Stack gap={0}>
          <Text size="xs" c="dimmed">
            P95
          </Text>
          <Text size="lg" className="num">
            {traced('p95', q.p95)}
          </Text>
        </Stack>
        {es != null && (
          <Stack gap={0}>
            <Text size="xs" c="dimmed">
              <Term name="ES95">ES95</Term>
            </Text>
            <Text size="lg" className="num">
              {traced('es95', es)}
            </Text>
          </Stack>
        )}
      </Group>
      <Stack gap={4} mt={4}>
        <IntervalBar p05={q.p05} p50={q.p50} p95={q.p95} tail={es} scale={scale} width="100%" />
        <Group justify="space-between">
          <Text size="xs" c="dimmed" className="num">
            {format(scale.lo)}
          </Text>
          <Text size="xs" c="dimmed" className="num">
            {format(scale.hi)}
          </Text>
        </Group>
      </Stack>
      <IntervalLegend tail={es != null} />
    </Stack>
  );
}
