import { Button, Group, Modal, Stack, Text, Textarea } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconArrowBackUp, IconCheck, IconX } from '@tabler/icons-react';
import { useState } from 'react';
import { useResumeApproval, type ApprovalDecision } from '../../../api/queries';
import type { Me } from '../../../api/types';
import { ErrorAlert } from '../../../components/ErrorAlert';
import { ActionBar } from '../../../components/Page';

const DECISIONS: Record<
  ApprovalDecision,
  { title: string; text: string; reason: string | null; hint: string; confirm: string; done: string }
> = {
  approve: {
    title: 'Утвердить отчёт?',
    text: 'Отчёт будет опубликован от вашего имени. Подписывается эта версия: если стресс-тест пересчитают, подпись на новую не перейдёт. Отменить решение нельзя.',
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
    <>
      <ActionBar
        id="decision"
        status={
          <>
            Подпишете как <Text span inherit fw={600} c="dark.8">{me.actor}</Text>
          </>
        }
        actions={
          <>
            <Button variant="subtle" color="gray" leftSection={<IconArrowBackUp size={16} />} onClick={() => setPending('return')}>
              Вернуть аналитику
            </Button>
            <Button variant="subtle" color="gray" leftSection={<IconX size={16} />} onClick={() => setPending('reject')}>
              Отклонить
            </Button>
            <Button color="mts" leftSection={<IconCheck size={16} />} onClick={() => setPending('approve')}>
              Утвердить отчёт
            </Button>
          </>
        }
      />

      <Modal opened={!!view} onClose={close} title={view?.title} centered size="lg" withCloseButton={false}>
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
    </>
  );
}
