import { Alert, Anchor, Button, Collapse, List, Stack, Text } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { IconArrowRight, IconRefresh } from '@tabler/icons-react';
import { useNavigate } from 'react-router';
import type { Artifacts, Me, RunStatus } from '../../api/types';
import { canApprove, canFixGraph } from '../../auth/session';
import { reasonText } from '../../lib/labels';
import type { Tab } from '../../lib/stages';
import type { RerunState } from '../../api/types';

/**
 * The one move forward for this person, shown at the end of the step line. The step itself
 * says what the run waits for, so the move needs no text of its own.
 */
export function NextMove({
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
    tab === target ? null : (
      <Button size="xs" rightSection={<IconArrowRight size={14} />} onClick={() => onTab(target)}>
        {text}
      </Button>
    );
  switch (status.status) {
    case 'queued':
    case 'running':
    case 'completed':
      return null;
    case 'human_fix_graph':
      return canFixGraph(me) ? go('scenario', 'Перейти к проверке') : null;
    case 'human_approval':
      return canApprove(me) ? go('report', 'Открыть отчёт') : null;
    default: {
      const state: RerunState = {
        portfolioId: artifacts?.portfolio_id ?? undefined,
        eventText: artifacts?.event_text ?? undefined,
        scenario: artifacts?.scenario?.text ?? undefined,
      };
      return (
        <Button size="xs" variant="default" leftSection={<IconRefresh size={14} />} onClick={() => navigate('/new', { state })}>
          Запустить заново
        </Button>
      );
    }
  }
}

/** Why a run stopped: the reasons in plain words, the technical text behind a link. */
export function StopReason({ status }: { status: RunStatus }) {
  const [open, { toggle }] = useDisclosure(false);
  if (['queued', 'running', 'completed', 'human_fix_graph', 'human_approval', 'rejected'].includes(status.status)) return null;
  const technical = [...(status.errors ?? []), status.error].filter((r): r is string => !!r);
  const human = [...new Set(technical.map(reasonText).filter((t): t is string => !!t))];
  if (!technical.length) return null;
  return (
    <Alert color="gray" title="Почему остановлен">
      <Stack gap={4}>
        {human.length > 0 && (
          <List size="sm" spacing={4}>
            {human.map((text) => (
              <List.Item key={text}>{text}</List.Item>
            ))}
          </List>
        )}
        <Anchor component="button" type="button" size="xs" c="dimmed" onClick={toggle} w="fit-content">
          {open ? 'Скрыть техническую причину' : 'Техническая причина'}
        </Anchor>
        <Collapse in={open}>
          <Text size="xs" c="dimmed" ff="monospace" style={{ whiteSpace: 'pre-wrap' }}>
            {technical.join('\n')}
          </Text>
        </Collapse>
      </Stack>
    </Alert>
  );
}
