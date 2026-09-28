import { Box, Group, Stack, Text } from '@mantine/core';
import type { ReactNode } from 'react';
import { bareChange, bareValue, change, metricValue } from '../lib/format';

export interface Scale {
  lo: number;
  hi: number;
}

/** One scale for a whole column, so intervals compare by eye; zero is always on it. */
export function scaleOf(values: (number | null | undefined)[]): Scale {
  const known = values.filter((v): v is number => v != null && Number.isFinite(v));
  const lo = Math.min(0, ...known);
  const hi = Math.max(0, ...known);
  return hi === lo ? { lo, hi: lo + 1 } : { lo, hi };
}

function at(value: number, scale: Scale): number {
  return ((value - scale.lo) / (scale.hi - scale.lo)) * 100;
}

/**
 * The P5–P95 interval as a band on the shared scale, with the median marked. With `base`, the
 * level before the event is drawn from zero in grey under it: how far the event moved it.
 * With `tail`, the mean of the worst 5 % (ES95) is marked by a dotted line.
 */
export function IntervalBar({
  p05,
  p50,
  p95,
  scale,
  width = 160,
  base,
  tail,
}: {
  p05: number;
  p50: number;
  p95: number;
  scale: Scale;
  width?: number | string;
  base?: number | null;
  tail?: number | null;
}) {
  const left = at(p05, scale);
  const right = at(p95, scale);
  const zero = at(0, scale);
  return (
    <Box
      pos="relative"
      h={14}
      w={width}
      aria-label={base != null ? 'Уровень до события и диапазон от P5 до P95 после него на общей шкале' : 'Диапазон от P5 до P95 на общей шкале'}
      role="img"
    >
      <Box pos="absolute" top={6} left={0} right={0} h={2} bg="gray.2" />
      {scale.lo < 0 && <Box pos="absolute" top={2} h={10} w={1} bg="gray.5" style={{ left: `${zero}%` }} />}
      {base != null && (
        <Box
          pos="absolute"
          top={4}
          h={6}
          bg="gray.4"
          style={{ left: `${Math.min(zero, at(base, scale))}%`, width: `${Math.abs(at(base, scale) - zero)}%`, borderRadius: 3 }}
        />
      )}
      <Box
        pos="absolute"
        top={4}
        h={6}
        bg="steel.3"
        style={{ left: `${left}%`, width: `${Math.max(right - left, 0.8)}%`, borderRadius: 3 }}
      />
      <Box
        pos="absolute"
        top={1}
        h={12}
        w={3}
        bg="steel.8"
        style={{ left: `calc(${at(p50, scale)}% - 1.5px)`, borderRadius: 2 }}
      />
      {tail != null && (
        <Box
          pos="absolute"
          top={1}
          h={12}
          style={{ left: `calc(${at(tail, scale)}% - 1px)`, borderLeft: '2px dotted var(--mantine-color-dark-4)' }}
        />
      )}
    </Box>
  );
}

/** What the marks of the bars mean, once above the bars that use them. */
export function IntervalLegend({ base = false, tail = false, note }: { base?: boolean; tail?: boolean; note?: string }) {
  const item = (mark: ReactNode, text: string) => (
    <Group gap={6} wrap="nowrap">
      {mark}
      <Text size="xs" c="dark.3">
        {text}
      </Text>
    </Group>
  );
  return (
    <Group gap="md" style={{ rowGap: 4 }}>
      {base && item(<Box w={16} h={6} bg="gray.4" style={{ borderRadius: 3 }} />, 'уровень до события')}
      {item(<Box w={16} h={6} bg="steel.3" style={{ borderRadius: 3 }} />, base ? 'P5–P95 после события' : 'P5–P95')}
      {item(<Box w={3} h={12} bg="steel.8" style={{ borderRadius: 2 }} />, base ? 'медиана после события' : 'медиана')}
      {tail && item(<Box h={12} style={{ borderLeft: '2px dotted var(--mantine-color-dark-4)' }} />, 'средние потери в худших 5 % (ES95)')}
      {note && (
        <Text size="xs" c="dark.3">
          {note}
        </Text>
      )}
    </Group>
  );
}

/** P50 in heavier type, P5 … P95 beside it: the interval is the result, never the point alone. */
export function IntervalText({
  p05,
  p50,
  p95,
  format,
  align = 'right',
}: {
  p05: number | null | undefined;
  p50: number | null | undefined;
  p95: number | null | undefined;
  format: (v: number | null | undefined) => string;
  align?: 'left' | 'right';
}) {
  return (
    <Stack gap={0} align={align === 'right' ? 'flex-end' : 'flex-start'} className="num">
      <Text fw={600} size="sm" style={{ whiteSpace: 'nowrap' }}>
        {format(p50)}
      </Text>
      <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
        {format(p05)} … {format(p95)}
      </Text>
    </Stack>
  );
}

export interface ShiftValues {
  /** The level before the event. */
  base: number;
  /** The change the event brings, by its quantiles. */
  p05: number;
  p50: number;
  p95: number;
  unit: string | null | undefined;
}

/**
 * A change read from the level it starts at: «5,02 → 68,98 %» — before the event and after it
 * by the median; below, the change with its P5 … P95, a fraction's in percentage points.
 */
export function ShiftText({ base, p05, p50, p95, unit, align = 'right' }: ShiftValues & { align?: 'left' | 'right' }) {
  return (
    <Stack gap={0} align={align === 'right' ? 'flex-end' : 'flex-start'} className="num">
      <Text fw={600} size="sm" style={{ whiteSpace: 'nowrap' }}>
        {bareValue(base, unit)} → {metricValue(base + p50, unit)}
      </Text>
      <Text size="xs" c="dimmed" ta={align}>
        <span style={{ whiteSpace: 'nowrap' }}>{change(p50, unit)}</span>{' '}
        <span style={{ whiteSpace: 'nowrap' }}>
          (P5–P95: {bareChange(p05, unit)} … {bareChange(p95, unit)})
        </span>
      </Text>
    </Stack>
  );
}

/** The change in words over the levels on the column's scale: before in grey, after as the band. */
export function Shift({ scale, width = '100%', ...values }: ShiftValues & { scale: Scale; width?: number | string }) {
  const { base, p05, p50, p95 } = values;
  return (
    <Stack gap={6} align="flex-end">
      <ShiftText {...values} />
      <IntervalBar base={base} p05={base + p05} p50={base + p50} p95={base + p95} scale={scale} width={width} />
    </Stack>
  );
}

export function Interval(props: {
  p05: number | null | undefined;
  p50: number | null | undefined;
  p95: number | null | undefined;
  scale: Scale;
  format: (v: number | null | undefined) => string;
  width?: number | string;
}) {
  const { p05, p50, p95, scale, format, width } = props;
  if (p05 == null || p50 == null || p95 == null) return <Text c="dimmed">—</Text>;
  return (
    <Group gap="md" wrap="nowrap" justify="flex-end">
      <IntervalText p05={p05} p50={p50} p95={p95} format={format} />
      <IntervalBar p05={p05} p50={p50} p95={p95} scale={scale} width={width} />
    </Group>
  );
}
