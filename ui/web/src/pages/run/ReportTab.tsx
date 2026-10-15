import { Center, Group, Loader, Paper, Stack, Table, Text, ThemeIcon } from '@mantine/core';
import { IconRosetteDiscountCheck } from '@tabler/icons-react';
import { useMemo } from 'react';
import { useReport } from '../../api/queries';
import type { Artifacts, Evidence } from '../../api/types';
import { canApprove, useSession } from '../../auth/session';
import { ErrorAlert } from '../../components/ErrorAlert';
import { ResultSummary } from '../../components/ResultSummary';
import { sliceSpec } from '../../api/catalog';
import { approver, day, percent, plural, timestamp } from '../../lib/format';
import { PageSection } from '../../components/Page';
import { AUTHORS, SOURCES, label } from '../../lib/labels';
import { hasReport } from '../../lib/stages';
import { pluginNotes } from '../../plugins';
import { DecisionPanel } from './DecisionPanel';
import { glossary, ReportText } from './ReportText';
import type { RunTabProps } from './RunPage';
import { useOrigins } from './useOrigins';

/** The seal: the second and last place MTS red appears. */
function Stamp({ artifacts }: { artifacts: Artifacts }) {
  return (
    <Paper p="md" style={{ borderLeft: '4px solid var(--msa-mts)' }}>
      <Group gap="md">
        <ThemeIcon size={40} radius="xl" color="mts" variant="light">
          <IconRosetteDiscountCheck size={24} />
        </ThemeIcon>
        <Stack gap={0}>
          <Text fw={600}>Отчёт утверждён</Text>
          <Text size="sm" c="dimmed">
            {approver(artifacts.approved_by)} · {timestamp(artifacts.approved_at)}
          </Text>
        </Stack>
      </Group>
    </Paper>
  );
}

function Assumptions({ items }: { items: Evidence[] }) {
  const grouped = new Map<string, { author: string; asOf: string; source: string; count: number }>();
  for (const e of items) {
    const key = [e.author, e.as_of, e.source_id].join('|');
    const row = grouped.get(key) ?? {
      author: e.author ? label(AUTHORS, e.author) : '—',
      asOf: day(e.as_of),
      source: label(SOURCES, e.source_id),
      count: 0,
    };
    row.count += 1;
    grouped.set(key, row);
  }
  return (
    <PageSection title="Допущения экспертов" hint="Кто и на какую дату ввёл числа, которых нет в документе события и исторических оценках." flush={grouped.size > 0}>
      {grouped.size === 0 ? (
        <Text size="sm" c="dimmed">
          Допущений экспертов нет: все параметры взяты из документа или исторических оценок.
        </Text>
      ) : (
        <Table verticalSpacing="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Автор</Table.Th>
              <Table.Th>На дату</Table.Th>
              <Table.Th>Источник</Table.Th>
              <Table.Th className="num-right">Параметров</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {[...grouped.values()].map((row) => (
              <Table.Tr key={`${row.author}${row.asOf}${row.source}`}>
                <Table.Td>{row.author}</Table.Td>
                <Table.Td>{row.asOf}</Table.Td>
                <Table.Td>{row.source}</Table.Td>
                <Table.Td className="num-right">{row.count}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </PageSection>
  );
}

export function ReportTab({ status, artifacts }: RunTabProps) {
  const { me } = useSession();
  const report = useReport(status, hasReport(status));
  const { entries } = useOrigins(status);
  const deciding = status.status === 'human_approval';
  const names = useMemo(() => glossary(artifacts), [artifacts]);
  const Notes = pluginNotes();

  if (report.error) return <ErrorAlert error={report.error} />;
  if (report.isPending) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }
  if (!report.data) return <Text c="dimmed">Отчёт появится, когда расчёт будет завершён.</Text>;
  const data = report.data;
  const headline = Object.values(artifacts.portfolio?.slices ?? {})
    .sort((a, b) => a.slice_id.localeCompare(b.slice_id))
    .find((item) => item.loss_quantiles);

  return (
    <Stack gap="lg">
      {status.status === 'completed' && <Stamp artifacts={artifacts} />}
      {headline && (
        <PageSection
          title={sliceSpec(headline.slice_id)?.label ?? headline.slice_id}
          aside={`${plural(headline.included.length, 'позиция', 'позиции', 'позиций')} в итоге · охват ${percent(headline.coverage.covered_share)}`}
        >
          <ResultSummary item={headline} artifacts={artifacts} entries={entries} />
        </PageSection>
      )}
      <PageSection title="Текст отчёта" hint="Так отчёт будет опубликован. Числа в тексте открывают своё происхождение.">
        <ReportText summary={data.summary} numbers={data.numbers} entries={entries} names={names} />
      </PageSection>
      <Assumptions items={data.assumptions} />
      {/* What the money figures rest on is in view before the signature. */}
      {Notes.map((Note, i) => (
        <Note key={i} artifacts={artifacts} />
      ))}
      {deciding &&
        (canApprove(me) && me ? (
          <DecisionPanel runId={status.run_id} me={me} />
        ) : (
          <Text c="dimmed">Утвердить, вернуть или отклонить отчёт может риск-менеджер.</Text>
        ))}
    </Stack>
  );
}
