import { Alert, Anchor, Button, Collapse, Group, List, Loader, Stack, Text } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import {
  IconAlertTriangle,
  IconArrowRight,
  IconCircleCheck,
  IconClock,
  IconInfoCircle,
  IconRefresh,
} from '@tabler/icons-react';
import type { ReactNode } from 'react';
import { useNavigate } from 'react-router';
import type { Artifacts, LlmWaiting, Me, RunStatus } from '../../api/types';
import { canApprove, canFixGraph } from '../../auth/session';
import { Elapsed } from '../../components/Elapsed';
import { approver, lowerFirst, timestamp } from '../../lib/format';
import { reasonText } from '../../lib/labels';
import { currentStage, llmDoing, nowText, stopOf, type Tab } from '../../lib/stages';
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
    <Alert color={color} variant="light" icon={icon} title={title} styles={{ title: { fontSize: 'var(--mantine-font-size-md)' } }}>
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
        <List size="sm" spacing={2}>
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

/** The model is working: shown while it answers, not only once it has answered. */
function Waiting({ waiting }: { waiting: LlmWaiting }) {
  return (
    <Group gap={8} wrap="nowrap">
      <Loader size={14} color="steel" />
      <Text size="sm">
        Языковая модель {llmDoing(waiting)} · <Elapsed since={waiting.started_at} />
      </Text>
    </Group>
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
    case 'queued':
    case 'running': {
      const waiting = status.llm_waiting && <Waiting waiting={status.llm_waiting} />;
      // The numbers are ready before the report: they are not held back while it is written.
      if (status.status === 'running' && currentStage(status, artifacts?.workflow) === 'report') {
        return (
          <Banner
            color="steel"
            icon={<IconClock />}
            title="Расчёт готов, пишется отчёт"
            action={go('portfolio', 'Открыть итоги')}
          >
            <Text size="sm">
              Итоги по позициям и срезам портфеля уже можно смотреть. Отчёт появится, когда модель допишет текст.
            </Text>
            {waiting}
          </Banner>
        );
      }
      const doing = nowText(status, artifacts?.workflow);
      return (
        <Banner color="steel" icon={<IconClock />} title="Идёт расчёт">
          <Text size="sm">
            Сейчас: {lowerFirst(doing)}. Страница обновляется сама; результаты появляются по мере готовности.
          </Text>
          {waiting}
        </Banner>
      );
    }
    case 'human_fix_graph': {
      const decision = stopOf(status)?.decision;
      const returned = decision?.outcome === 'returned';
      // On the graph tab the stop explains itself; a second banner would repeat it.
      if (canFixGraph(me) && tab === 'scenario') return null;
      if (!canFixGraph(me)) {
        return (
          <Banner color="gray" icon={<IconInfoCircle />} title="Аналитик проверяет граф и сценарий">
            <Text size="sm">Отчёт появится после расчёта по позициям.</Text>
          </Banner>
        );
      }
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
      if (canApprove(me) && tab === 'report') return null;
      if (!canApprove(me)) {
        return (
          <Banner color="gray" icon={<IconInfoCircle />} title="Отчёт на утверждении">
            <Text size="sm">Решение принимает риск-менеджер.</Text>
          </Banner>
        );
      }
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
    case 'completed':
      // On the report the stamp says it; the banner is for the other tabs.
      if (tab === 'report') return null;
      return (
        <Banner color="teal" icon={<IconCircleCheck />} title="Отчёт утверждён">
          <Text size="sm">
            {approver(artifacts?.approved_by)}, {timestamp(artifacts?.approved_at)}.
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
