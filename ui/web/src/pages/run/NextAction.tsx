import { Alert, Anchor, Button, Collapse, Group, List, Stack, Text } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { IconAlertTriangle, IconArrowRight, IconInfoCircle, IconRefresh } from '@tabler/icons-react';
import type { ReactNode } from 'react';
import { useNavigate } from 'react-router';
import type { Artifacts, Me, RunStatus } from '../../api/types';
import { canApprove, canFixGraph } from '../../auth/session';
import { reasonText } from '../../lib/labels';
import { stopOf, type Tab } from '../../lib/stages';
import type { RerunState } from '../NewRun';

function Banner({
  color,
  icon,
  title,
  children,
  action,
}: {
  color: string;
  icon: ReactNode;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <Alert color={color} icon={icon} title={title}>
      <Group justify="space-between" align="flex-end" gap="md">
        <Stack gap={4} style={{ flex: 1, minWidth: 240 }}>
          {children}
        </Stack>
        {action}
      </Group>
    </Alert>
  );
}

function Failure({ status, rerun }: { status: RunStatus; rerun: ReactNode }) {
  const [open, { toggle }] = useDisclosure(false);
  const technical = [...(status.errors ?? []), status.error].filter((r): r is string => !!r);
  const human = [...new Set(technical.map(reasonText).filter((t): t is string => !!t))];
  return (
    <Banner color="gray" icon={<IconAlertTriangle />} title="Стресс-тест остановлен" action={rerun}>
      <Text size="sm">
        Автоматическая обработка не смогла продолжить. Уточните текст события или данные портфеля и
        запустите стресс-тест заново.
      </Text>
      {human.length > 0 && (
        <List size="sm" spacing={4}>
          {human.map((text) => (
            <List.Item key={text}>{text}</List.Item>
          ))}
        </List>
      )}
      {technical.length > 0 && (
        <>
          <Anchor component="button" type="button" size="xs" c="dimmed" onClick={toggle} w="fit-content">
            {open ? 'Скрыть техническую причину' : 'Техническая причина'}
          </Anchor>
          <Collapse in={open}>
            <Text size="xs" c="dimmed" ff="monospace" style={{ whiteSpace: 'pre-wrap' }}>
              {technical.join('\n')}
            </Text>
          </Collapse>
        </>
      )}
    </Banner>
  );
}

/** One message about what happens next, and the one move forward for this person. */
export function NextAction({
  status,
  artifacts,
  me,
  tab,
  onTab,
}: {
  status: RunStatus;
  artifacts: Artifacts | undefined;
  me: Me | null;
  tab: Tab;
  onTab: (tab: Tab) => void;
}) {
  const navigate = useNavigate();
  const go = (target: Tab, text: string) =>
    tab === target ? undefined : (
      <Button rightSection={<IconArrowRight size={16} />} onClick={() => onTab(target)}>
        {text}
      </Button>
    );
  const rerunState: RerunState = {
    portfolioId: artifacts?.portfolio_id ?? undefined,
    eventText: artifacts?.event_text ?? undefined,
    scenario: artifacts?.scenario?.text ?? undefined,
  };
  const rerun = (
    <Button
      variant="default"
      leftSection={<IconRefresh size={16} />}
      onClick={() => navigate('/new', { state: rerunState })}
    >
      Запустить заново
    </Button>
  );

  switch (status.status) {
    // The step bar already shows the stage under way, whom the run waits for and who approved
    // the report; a banner is only for a move this person can make.
    case 'queued':
    case 'running':
    case 'completed':
      return null;
    case 'human_fix_graph': {
      const decision = stopOf(status)?.decision;
      const returned = decision?.outcome === 'returned';
      // On the graph tab the stop explains itself; a second banner would repeat it.
      if (!canFixGraph(me) || tab === 'scenario') return null;
      return (
        <Banner
          color="yellow"
          icon={<IconAlertTriangle />}
          title={returned ? 'Риск-менеджер вернул отчёт на доработку' : 'Нужна ваша проверка'}
          action={go('scenario', 'Перейти к проверке')}
        >
          <Text size="sm">
            {returned
              ? 'Прочитайте причину возврата, поправьте граф или сценарий и подтвердите: расчёт пройдёт заново.'
              : 'Проверьте граф влияния и сценарий шоков, затем подтвердите их — после этого начнётся расчёт по позициям.'}
          </Text>
        </Banner>
      );
    }
    case 'human_approval':
      // On the report the decision panel is the move forward; a banner would repeat it.
      if (!canApprove(me) || tab === 'report') return null;
      return (
        <Banner
          color="yellow"
          icon={<IconAlertTriangle />}
          title="Отчёт ждёт вашего решения"
          action={go('report', 'Открыть отчёт')}
        >
          <Text size="sm">
            Прочитайте отчёт и примите решение: утвердить, вернуть аналитику на доработку или отклонить.
            Граф, позиции и срезы портфеля доступны на соседних вкладках.
          </Text>
        </Banner>
      );
    case 'rejected':
      return (
        <Banner color="gray" icon={<IconInfoCircle />} title="Отчёт отклонён риск-менеджером" action={rerun}>
          <Text size="sm">Чтобы получить новую оценку, запустите стресс-тест заново с уточнённым текстом события.</Text>
        </Banner>
      );
    default:
      return <Failure status={status} rerun={rerun} />;
  }
}
