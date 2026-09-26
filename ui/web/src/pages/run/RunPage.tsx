import {
  ActionIcon,
  Alert,
  Anchor,
  Center,
  CopyButton,
  Group,
  Loader,
  Spoiler,
  Stack,
  Tabs,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';
import { IconArrowLeft, IconCheck, IconCopy } from '@tabler/icons-react';
import { useQueryClient } from '@tanstack/react-query';
import { lazy, Suspense, useEffect } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';
import { useArtifacts, useRunStatus } from '../../api/queries';
import type { Artifacts, RunRow, RunStatus } from '../../api/types';
import { useSession } from '../../auth/session';
import { ErrorAlert } from '../../components/ErrorAlert';
import { RunArtifacts } from '../../components/Provenance';
import { day, shorten, timestamp } from '../../lib/format';
import { TABS, available, defaultTab, steps, type Tab } from '../../lib/stages';
import { ActivityTab } from './ActivityTab';
import { ExplainTab } from './ExplainTab';
import { NextAction } from './NextAction';
import { PortfolioTab } from './PortfolioTab';
import { PositionsTab } from './positions/PositionsTab';
import { ProvenanceTab } from './ProvenanceTab';
import { ReportTab } from './ReportTab';
import { RunSteps } from './RunSteps';

// The graph canvas is the heaviest part of the page; it loads with its tab.
const ScenarioTab = lazy(() => import('./scenario/ScenarioTab').then((m) => ({ default: m.ScenarioTab })));

export interface RunTabProps {
  status: RunStatus;
  artifacts: Artifacts;
}

function Masthead({ status, artifacts }: RunTabProps) {
  const { mode } = useSession();
  const row = useQueryClient()
    .getQueryData<RunRow[]>(['runs', mode])
    ?.find((r) => r.run_id === status.run_id);
  const event = (artifacts.event_text ?? '').trim();
  return (
    <Stack gap="xs">
      <Anchor component={Link} to="/" size="sm" w="fit-content">
        <Group gap={4}>
          <IconArrowLeft size={14} /> Все стресс-тесты
        </Group>
      </Anchor>
      <Title order={3} fw={600} style={{ lineHeight: 1.35 }}>
        {shorten(event, 180) || 'Стресс-тест'}
      </Title>
      {event.length > 180 && (
        <Spoiler maxHeight={0} showLabel="Показать текст события полностью" hideLabel="Скрыть">
          <Text size="sm" c="dark.6" maw="80ch" style={{ whiteSpace: 'pre-wrap' }}>
            {event}
          </Text>
        </Spoiler>
      )}
      {/* Where the run stands is the step bar below; the header only says what it is. */}
      <Group gap="md" c="dark.3">
        <Text size="sm">Портфель {artifacts.portfolio_id ?? '—'}</Text>
        {artifacts.snapshot && (
          <Text size="sm">
            Данные: {artifacts.snapshot.label}, на {day(artifacts.snapshot.as_of)}
          </Text>
        )}
        {row && (
          <Text size="sm">
            Запущен {timestamp(row.created_at)}
            {row.created_by ? ` · ${row.created_by}` : ''}
          </Text>
        )}
        <Group gap={2}>
          <Text size="xs" ff="monospace">
            {status.run_id}
          </Text>
          <CopyButton value={status.run_id}>
            {({ copied, copy }) => (
              <Tooltip label={copied ? 'Скопировано' : 'Скопировать номер'}>
                <ActionIcon variant="subtle" color="gray" size="sm" onClick={copy} aria-label="Скопировать номер">
                  {copied ? <IconCheck size={14} /> : <IconCopy size={14} />}
                </ActionIcon>
              </Tooltip>
            )}
          </CopyButton>
        </Group>
      </Group>
    </Stack>
  );
}

export function RunPage() {
  const { runId = '' } = useParams();
  const { me } = useSession();
  const status = useRunStatus(runId);
  const artifacts = useArtifacts(status.data);
  const [params, setParams] = useSearchParams();
  const asked = params.get('tab') as Tab | null;

  // A run opens where this person is needed; after that the tab is theirs to choose.
  useEffect(() => {
    if (!asked && status.data && artifacts.data) {
      setParams({ tab: defaultTab(status.data, artifacts.data) }, { replace: true });
    }
  }, [asked, status.data, artifacts.data, setParams]);

  if (status.error) {
    return (
      <Stack>
        <ErrorAlert error={status.error} />
        <Anchor component={Link} to="/">
          К списку стресс-тестов
        </Anchor>
      </Stack>
    );
  }
  if (!status.data || !artifacts.data) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }

  const data = { status: status.data, artifacts: artifacts.data };
  const tab: Tab = asked && TABS.some((t) => t.value === asked) ? asked : defaultTab(data.status, data.artifacts);
  const setTab = (next: Tab) => setParams({ tab: next });

  return (
    <RunArtifacts.Provider value={data.artifacts}>
    <Stack gap="lg">
      <Masthead {...data} />
      {!!data.artifacts.scenario_warnings?.length && (
        <Alert color="orange" title="Сценарий не охватывает затронутые позиции">
          <Stack gap="xs">
            {data.artifacts.scenario_warnings.map((warning, index) => <Text size="sm" key={index}>{warning.message}</Text>)}
            <Anchor component="button" size="sm" onClick={() => setTab('scenario')} w="fit-content">Открыть сценарий</Anchor>
          </Stack>
        </Alert>
      )}
      <RunSteps steps={steps(data.status, data.artifacts, me)} />
      <NextAction {...data} me={me} tab={tab} onTab={setTab} />
      <Tabs value={tab} onChange={(value) => value && setTab(value as Tab)} keepMounted={false}>
        <Tabs.List>
          {TABS.map(({ value, title, empty }) => {
            const ready = available(value, data.status, data.artifacts);
            const item = (
              <Tabs.Tab key={value} value={value} disabled={!ready}>
                {title}
              </Tabs.Tab>
            );
            return ready ? (
              item
            ) : (
              <Tooltip key={value} label={empty}>
                <span>{item}</span>
              </Tooltip>
            );
          })}
        </Tabs.List>
        <Tabs.Panel value="scenario" pt="lg">
          <Suspense
            fallback={
              <Center py="xl">
                <Loader />
              </Center>
            }
          >
            <ScenarioTab {...data} />
          </Suspense>
        </Tabs.Panel>
        <Tabs.Panel value="positions" pt="lg">
          <PositionsTab {...data} />
        </Tabs.Panel>
        <Tabs.Panel value="portfolio" pt="lg">
          <PortfolioTab {...data} />
        </Tabs.Panel>
        <Tabs.Panel value="report" pt="lg">
          <ReportTab {...data} />
        </Tabs.Panel>
        <Tabs.Panel value="provenance" pt="lg">
          <ProvenanceTab {...data} />
        </Tabs.Panel>
        <Tabs.Panel value="explain" pt="lg">
          <ExplainTab {...data} />
        </Tabs.Panel>
        <Tabs.Panel value="activity" pt="lg">
          <ActivityTab {...data} />
        </Tabs.Panel>
      </Tabs>
    </Stack>
    </RunArtifacts.Provider>
  );
}
