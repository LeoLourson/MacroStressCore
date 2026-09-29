import { Badge, Group, Text, Tooltip } from '@mantine/core';
import { IconAlertTriangle, IconCheck, IconX } from '@tabler/icons-react';
import { flagKind } from '../api/catalog';
import type { CalculationResult } from '../api/types';
import { EXECUTION, RESULT_STATUS, flagList, flagOne, label } from '../lib/labels';

/** Why a result is not plainly ok: the flags that sent it to review, else its model's errors and warnings. */
export function statusReasons(result: CalculationResult, shocks?: Record<string, string>): string[] {
  if (result.status === 'ok') return [];
  const review = result.flags.filter((f) => flagKind(f) === 'review').map((f) => flagOne(f, shocks));
  if (review.length) return [...new Set(review)];
  return [...new Set(result.diagnostics.filter((d) => d.severity !== 'info').map((d) => d.message || d.code))];
}

/** The status in a word with its mark; a status other than ok says why, when told. */
export function ResultStatus({ status, reasons = [], size = 'sm' }: { status: string; reasons?: string[]; size?: 'xs' | 'sm' }) {
  const ok = status === 'ok';
  return (
    <Group gap={4} wrap="nowrap" align="flex-start" c={ok ? 'teal.9' : 'dark.6'}>
      {ok ? <IconCheck size={14} style={{ flexShrink: 0, marginTop: 3 }} /> : <IconAlertTriangle size={14} style={{ flexShrink: 0, marginTop: 3 }} />}
      <Text size={size}>
        <Text span inherit fw={ok ? 400 : 600} style={{ whiteSpace: 'nowrap' }}>
          {label(RESULT_STATUS, status)}
        </Text>
        {reasons.length > 0 && (
          <Text span inherit c="dark.4">
            {': '}
            {reasons.join('; ')}
          </Text>
        )}
      </Text>
    </Group>
  );
}

/** Whether the position was calculated at all; a position that was not says why. */
export function ExecutionBadge({ result }: { result: CalculationResult }) {
  if (result.execution === 'completed') return <ResultStatus status={result.status} />;
  const why = [
    ...result.diagnostics.filter((d) => d.severity === 'error').map((d) => d.message || d.code),
    ...flagList(result.flags),
  ];
  return (
    <Tooltip label={[...new Set(why)].join('; ') || 'Расчёт не выполнен'} multiline maw={420}>
      <Badge color="gray" c="gray.9" variant="light" tt="none" fw={500} leftSection={<IconX size={12} />}>
        {label(EXECUTION, result.execution)}
      </Badge>
    </Tooltip>
  );
}
