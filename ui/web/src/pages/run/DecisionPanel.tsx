import { Button, Group, Modal, Paper, Stack, Text, Textarea, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconArrowBackUp, IconCheck, IconX } from '@tabler/icons-react';
import { useState } from 'react';
import { useResumeApproval, type ApprovalDecision } from '../../api/queries';
import type { Me } from '../../api/types';
import { ErrorAlert } from '../../components/ErrorAlert';

const DECISIONS: Record<
  ApprovalDecision,
  { title: string; text: string; reason: string | null; hint: string; confirm: string; done: string }
> = {
  approve: {
    title: 'Утвердить отчёт?',
    text: 'Отчёт будет опубликован от вашего имени. Отменить решение нельзя.',
    reason: null,
    hint: 'Комментарий к утверждению (необязательно)',
    confirm: 'Утвердить и опубликовать',
    done: 'Отчёт утверждён',
  },
  return: {
    title: 'Вернуть аналитику на доработку?',
    text: 'Аналитик увидит вашу причину, поправит граф или сценарий, стресс-тест пересчитается и снова придёт к вам на решение.',
    reason: 'Что нужно переделать',
    hint: 'Например: сценарий задержки расчётов слишком мягкий, возьмите 45–90 дней',
    confirm: 'Вернуть аналитику',
    done: 'Отчёт возвращён аналитику',
  },
  reject: {
    title: 'Отклонить отчёт насовсем?',
    text: 'Стресс-тест закроется без публикации; граф и расчёт не сохранятся для доработки. Чтобы получить оценку, его придётся запустить заново.',
    reason: 'Почему оценка не нужна',
    hint: 'Причина останется в журнале решений',
    confirm: 'Отклонить отчёт',
    done: 'Отчёт отклонён',
  },
};

/** The approval gate: three outcomes of different weight, each confirmed before it is sent. */
export function DecisionPanel({ runId, me }: { runId: string; me: Me }) {
  const [pending, setPending] = useState<ApprovalDecision | null>(null);
  const [reason, setReason] = useState('');
  const resume = useResumeApproval(runId);
  const view = pending ? DECISIONS[pending] : null;
  const required = !!view?.reason;
  const close = () => {
    setPending(null);
    setReason('');
    resume.reset();
  };
  const confirm = () => {
    if (!pending || (required && !reason.trim())) return;
    resume.mutate(
      { decision: pending, reason: reason.trim() || undefined },
      {
        onSuccess: () => {
          notifications.show({ message: DECISIONS[pending].done, color: 'teal' });
          close();
        },
      },
    );
  };

  return (
    <Paper p="lg" id="decision" style={{ borderColor: 'var(--mantine-color-gray-4)' }}>
      <Stack gap="md">
        <Stack gap={4}>
          <Title order={4}>Решение по отчёту</Title>
          <Text size="sm" c="dimmed" maw="72ch">
            Подпишет: <b>{me.actor}</b>. Подписывается именно эта версия отчёта: если стресс-тест
            пересчитают, подпись на новую версию не перейдёт.
          </Text>
        </Stack>
        <Group justify="space-between">
          <Group>
            <Button size="md" leftSection={<IconCheck size={18} />} onClick={() => setPending('approve')}>
              Утвердить отчёт
            </Button>
            <Button
              size="md"
              variant="default"
              leftSection={<IconArrowBackUp size={18} />}
              onClick={() => setPending('return')}
            >
              Вернуть аналитику
            </Button>
          </Group>
          <Button variant="subtle" color="gray" leftSection={<IconX size={16} />} onClick={() => setPending('reject')}>
            Отклонить
          </Button>
        </Group>
      </Stack>

      <Modal opened={!!view} onClose={close} title={view?.title} centered size="lg">
        {view && (
          <Stack>
            <Text size="sm">{view.text}</Text>
            <Textarea
              label={view.reason ?? view.hint}
              placeholder={view.reason ? view.hint : undefined}
              required={required}
              autosize
              minRows={3}
              value={reason}
              onChange={(e) => setReason(e.currentTarget.value)}
              data-autofocus
            />
            {resume.error && <ErrorAlert error={resume.error} />}
            <Group justify="flex-end">
              <Button variant="default" onClick={close}>
                Отмена
              </Button>
              <Button
                color={pending === 'approve' ? 'mts' : pending === 'reject' ? 'dark' : 'steel'}
                disabled={required && !reason.trim()}
                loading={resume.isPending}
                onClick={confirm}
              >
                {view.confirm}
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </Paper>
  );
}
