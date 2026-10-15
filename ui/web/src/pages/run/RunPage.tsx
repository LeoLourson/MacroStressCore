import {
  ActionIcon,
  Alert,
  Anchor,
  Box,
  Center,
  CopyButton,
  Group,
  Loader,
  ScrollArea,
  Stack,
  SegmentedControl,
  Text,
  Tooltip,
} from '@mantine/core';
import { IconCheck, IconCopy, IconAlertTriangle } from '@tabler/icons-react';
import { Fragment, lazy, Suspense, useEffect, type ReactNode } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';
import { useArtifacts, usePortfolios, useRuns, useRunStatus } from '../../api/queries';
import type { Artifacts, RunStatus } from '../../api/types';
import { useSession } from '../../auth/session';
import { ErrorAlert } from '../../components/ErrorAlert';
import { RunArtifacts } from '../../components/Provenance';
import { PageHeader } from '../../components/Page';
import { Hint } from '../../components/Term';
import { day, timestamp } from '../../lib/format';
import { TABS, available, defaultTab, steps, type Tab } from '../../lib/stages';
import { ActivityTab } from './ActivityTab';
import { ExplainTab } from './ExplainTab';
import { NextMove, StopReason } from './NextAction';
import { PortfolioTab } from './PortfolioTab';
import { PositionsTab } from './positions/PositionsTab';
import { ReportTab } from './ReportTab';
import { RunSteps } from './RunSteps';
import { SourcesTab } from './SourcesTab';

// The graph canvas is the heaviest part of the page; it loads with its tab.
const ScenarioTab = lazy(() => import('./scenario/ScenarioTab').then((m) => ({ default: m.ScenarioTab })));

export interface RunTabProps {
  status: RunStatus;
  artifacts: Artifacts;
}

function Masthead({ status, artifacts }: RunTabProps) {
  // Who started the run and when come from the list, loaded once when the page opens by a link.
  const row = useRuns(false).data?.find((r) => r.run_id === status.run_id);
  const portfolioId = artifacts.portfolio_id;
  const portfolio = usePortfolios(!!portfolioId).data?.find((p) => p.portfolio_id === portfolioId);
  const event = (artifacts.event_text ?? '').trim();
  const snapshot = artifacts.snapshot;
  // Where the run stands is the step bar below; the header only says what it is.
  const facts: ReactNode[] = [
    portfolioId && `Портфель «${portfolio?.name || portfolioId}»`,
    snapshot && <Hint text={snapshot.label}>данные на {day(snapshot.as_of)}</Hint>,
    row && `запущен ${timestamp(row.created_at)}${row.created_by ? `, ${row.created_by}` : ''}`,
  ].filter(Boolean);
  const copy = (
    <CopyButton value={status.run_id}>
      {({ copied, copy }) => (
        <Tooltip label={copied ? 'Номер скопирован' : `Скопировать номер стресс-теста ${status.run_id}`}>
          <ActionIcon variant="subtle" color="gray" size="sm" onClick={copy} aria-label="Скопировать номер стресс-теста">
            {copied ? <IconCheck size={14} /> : <IconCopy size={14} />}
          </ActionIcon>
        </Tooltip>
      )}
    </CopyButton>
  );
  return (
    <PageHeader
      title={
        <Text inherit lineClamp={1} title={event}>
          {event || 'Стресс-тест'}
        </Text>
      }
      meta={
        <Group gap={4} wrap="nowrap" align="center">
          <span>
            {facts.map((fact, index) => (
              <Fragment key={index}>
                {index > 0 && ' · '}
                {fact}
              </Fragment>
            ))}
          </span>
          {copy}
        </Group>
      }
    />
  );
}

function Panel({ tab, ...data }: RunTabProps & { tab: Tab }) {
  switch (tab) {
    case 'scenario':
      return (
        <Suspense
          fallback={
            <Center py="xl">
              <Loader />
            </Center>
          }
        >
          <ScenarioTab {...data} />
        </Suspense>
      );
    case 'positions':
      return <PositionsTab {...data} />;
    case 'portfolio':
      return <PortfolioTab {...data} />;
    case 'report':
      return <ReportTab {...data} />;
    case 'sources':
      return <SourcesTab {...data} />;
    case 'explain':
      return <ExplainTab {...data} />;
    case 'activity':
      return <ActivityTab {...data} />;
  }
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
    <Stack gap="md">
      <Masthead {...data} />
      {!!data.artifacts.scenario_warnings?.length && (
        <Alert icon={<IconAlertTriangle size={16} />} color="orange" py="xs">
          <Group gap="xs" wrap="nowrap" align="flex-start" justify="space-between">
            <Text size="sm">
              Сценарий не охватывает затронутые позиции:{' '}
              {data.artifacts.scenario_warnings.map((warning) => warning.message).join(' ')}
            </Text>
            <Anchor component="button" size="sm" onClick={() => setTab('scenario')} style={{ whiteSpace: 'nowrap' }}>
              Открыть сценарий
            </Anchor>
          </Group>
        </Alert>
      )}
      <RunSteps
        steps={steps(data.status, data.artifacts, me)}
        action={<NextMove {...data} me={me} tab={tab} onTab={setTab} />}
      />
      <StopReason status={data.status} />
      {/* The same switch as every other in the app, as wide as the content it switches; on a phone it scrolls sideways. */}
      <ScrollArea mt="xs" type="auto" scrollbars="x" offsetScrollbars>
        <SegmentedControl
          fullWidth
          value={tab}
          onChange={(value) => setTab(value as Tab)}
          aria-label="Разделы стресс-теста"
          data={TABS.map(({ value, title, empty }) => {
            const ready = available(value, data.status, data.artifacts);
            return { value, disabled: !ready, label: ready ? title : <span title={empty}>{title}</span> };
          })}
        />
      </ScrollArea>
      <Box pt="xs">
        <Panel tab={tab} {...data} />
      </Box>
    </Stack>
    </RunArtifacts.Provider>
  );
}
