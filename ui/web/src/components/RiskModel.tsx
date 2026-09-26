import { Badge, Group, Text, Tooltip } from '@mantine/core';
import { IconAlertTriangle, IconCheck, IconX } from '@tabler/icons-react';
import type { CalculationResult } from '../api/types';
import { EXECUTION, RESULT_STATUS, flagList, label } from '../lib/labels';

export function ResultStatus({ status }: { status: string }) {
  const ok = status === 'ok';
  return (
    <Group gap={4} wrap="nowrap" c={ok ? 'teal.9' : 'dark.6'}>
      {ok ? <IconCheck size={14} /> : <IconAlertTriangle size={14} />}
      <Text size="sm" fw={ok ? 400 : 600} style={{ whiteSpace: 'nowrap' }}>
        {label(RESULT_STATUS, status)}
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
