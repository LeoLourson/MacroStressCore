import { Badge } from '@mantine/core';
import {
  IconAlertTriangle,
  IconCheck,
  IconClock,
  IconEye,
  IconPlayerPlay,
  IconSignature,
  IconX,
} from '@tabler/icons-react';
import type { RunState } from '../api/types';

// Every state carries an icon and words; colour only repeats what they already say.
const STATES: Record<RunState, { text: string; color: string; Icon: typeof IconCheck }> = {
  queued: { text: 'В очереди', color: 'gray', Icon: IconClock },
  running: { text: 'Идёт расчёт', color: 'steel', Icon: IconPlayerPlay },
  human_fix_graph: { text: 'Проверка графа', color: 'yellow', Icon: IconEye },
  human_approval: { text: 'Ждёт решения', color: 'yellow', Icon: IconSignature },
  completed: { text: 'Утверждён', color: 'teal', Icon: IconCheck },
  rejected: { text: 'Отклонён', color: 'gray', Icon: IconX },
  failed: { text: 'Остановлен', color: 'gray', Icon: IconAlertTriangle },
};

export function statusText(state: RunState): string {
  return STATES[state]?.text ?? state;
}

export function StatusBadge({ state, size = 'md' }: { state: RunState; size?: 'sm' | 'md' | 'lg' }) {
  const { text, color, Icon } = STATES[state] ?? STATES.failed;
  return (
    <Badge
      variant="light"
      color={color}
      c={color === 'yellow' ? 'dark.7' : `${color}.9`}
      size={size}
      radius="sm"
      tt="none"
      fw={500}
      leftSection={<Icon size={14} stroke={2} />}
    >
      {text}
    </Badge>
  );
}
