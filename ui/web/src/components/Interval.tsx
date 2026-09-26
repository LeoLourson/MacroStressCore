import { Box, Group, Stack, Text } from '@mantine/core';

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

/** The P5–P95 interval as a line on the shared scale, with the median marked. */
export function IntervalBar({
  p05,
  p50,
  p95,
  scale,
  width = 160,
}: {
  p05: number;
  p50: number;
  p95: number;
  scale: Scale;
  width?: number | string;
}) {
  const left = at(p05, scale);
  const right = at(p95, scale);
  const zero = at(0, scale);
  return (
    <Box
      pos="relative"
      h={14}
      w={width}
      aria-label={`Диапазон от P5 до P95 на общей шкале`}
      role="img"
    >
      <Box pos="absolute" top={6} left={0} right={0} h={2} bg="gray.2" />
      {scale.lo < 0 && <Box pos="absolute" top={2} h={10} w={1} bg="gray.5" style={{ left: `${zero}%` }} />}
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
    </Box>
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
