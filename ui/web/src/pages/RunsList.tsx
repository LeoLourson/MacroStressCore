import {
  Button,
  Center,
  Group,
  Loader,
  Paper,
  SegmentedControl,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { IconArrowRight, IconPlus, IconSearch } from '@tabler/icons-react';
import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { usePortfolios, useRuns } from '../api/queries';
import type { Me, RunRow } from '../api/types';
import { canApprove, canFixGraph, canRun, useSession } from '../auth/session';
import { ErrorAlert } from '../components/ErrorAlert';
import { StatusBadge } from '../components/StatusBadge';
import { approver, shorten, timestamp } from '../lib/format';
import { ACTIVE } from '../lib/stages';

function waitsFor(row: RunRow, me: Me | null): string | null {
  if (row.status === 'human_fix_graph' && canFixGraph(me)) return 'Проверить граф и сценарий';
  if (row.status === 'human_approval' && canApprove(me)) return 'Принять решение по отчёту';
  return null;
}

type Filter = 'all' | 'active' | 'waiting' | 'done';

const FILTERS: { value: Filter; label: string }[] = [
  { value: 'all', label: 'Все' },
  { value: 'active', label: 'В работе' },
  { value: 'waiting', label: 'Ждут действия' },
  { value: 'done', label: 'Завершены' },
];

function matches(row: RunRow, filter: Filter): boolean {
  switch (filter) {
    case 'active':
      return ACTIVE.includes(row.status);
    case 'waiting':
      return row.status === 'human_fix_graph' || row.status === 'human_approval';
    case 'done':
      return ['completed', 'rejected', 'failed'].includes(row.status);
    default:
      return true;
  }
}

function usePortfolioName(): (id: string) => string | undefined {
  const portfolios = usePortfolios(true).data;
  return (id) => portfolios?.find((p) => p.portfolio_id === id)?.name || undefined;
}

function PortfolioCell({ id, name }: { id: string; name?: string }) {
  return (
    <>
      <Text size="sm">{name ?? id}</Text>
      {name && (
        <Text size="xs" c="dimmed" ff="monospace">
          {id}
        </Text>
      )}
    </>
  );
}

function Attention({ rows, me }: { rows: RunRow[]; me: Me | null }) {
  const nameOf = usePortfolioName();
  const navigate = useNavigate();
  const waiting = rows.filter((row) => waitsFor(row, me));
  if (!waiting.length) return null;
  return (
    <Stack gap="xs">
      <Title order={4}>Ждут вашего действия</Title>
      <Paper>
        {waiting.map((row, index) => (
          <Group
            key={row.run_id}
            justify="space-between"
            wrap="nowrap"
            p="md"
            style={index ? { borderTop: '1px solid var(--mantine-color-gray-3)' } : undefined}
          >
            <Stack gap={4} miw={0}>
              <Text fw={500} lineClamp={1}>
                {shorten(row.event_text, 160)}
              </Text>
              <Text size="sm" c="dimmed">
                Портфель «{nameOf(row.portfolio_id) ?? row.portfolio_id}» · запущен {timestamp(row.created_at)}
              </Text>
            </Stack>
            <Button
              variant="light"
              rightSection={<IconArrowRight size={16} />}
              onClick={() => navigate(`/runs/${row.run_id}`)}
              style={{ flexShrink: 0 }}
            >
              {waitsFor(row, me)}
            </Button>
          </Group>
        ))}
      </Paper>
    </Stack>
  );
}

export function RunsList() {
  const { me } = useSession();
  const navigate = useNavigate();
  const runs = useRuns();
  const [filter, setFilter] = useState<Filter>('all');
  const [search, setSearch] = useState('');
  const nameOf = usePortfolioName();

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return (runs.data ?? []).filter(
      (row) =>
        matches(row, filter) &&
        (!needle ||
          row.event_text.toLowerCase().includes(needle) ||
          row.portfolio_id.toLowerCase().includes(needle) ||
          (nameOf(row.portfolio_id) ?? '').toLowerCase().includes(needle)),
    );
  }, [runs.data, filter, search, nameOf]);

  return (
    <Stack gap="xl">
      <Group justify="space-between" align="flex-end">
        <Stack gap={4}>
          <Title order={2}>Стресс-тесты</Title>
          <Text c="dimmed">Как одно событие повлияет на портфель: граф влияния, расчёт позиций, отчёт.</Text>
        </Stack>
        {canRun(me) && (
          <Button
            component={Link}
            to="/new"
            leftSection={<IconPlus size={18} />}
          >
            Новый стресс-тест
          </Button>
        )}
      </Group>

      {runs.error && <ErrorAlert error={runs.error} />}
      {runs.isPending ? (
        <Center py="xl">
          <Loader />
        </Center>
      ) : (
        <>
          <Attention rows={runs.data ?? []} me={me} />
          <Stack gap="sm">
            <Group justify="space-between">
              <SegmentedControl value={filter} onChange={(v) => setFilter(v as Filter)} data={FILTERS} />
              <TextInput
                placeholder="Поиск по событию или портфелю"
                leftSection={<IconSearch size={16} />}
                value={search}
                onChange={(e) => setSearch(e.currentTarget.value)}
                w={{ base: '100%', sm: 320 }}
              />
            </Group>
            <Paper>
              {rows.length === 0 ? (
                <Text className="empty">
                  {(runs.data ?? []).length === 0
                    ? 'Стресс-тестов пока нет.'
                    : 'Под выбранные условия ничего не подходит.'}
                </Text>
              ) : (
                <Table.ScrollContainer minWidth={760}>
                  <Table verticalSpacing="sm" horizontalSpacing="md" highlightOnHover>
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>Событие</Table.Th>
                        <Table.Th w={170}>Статус</Table.Th>
                        <Table.Th w={180}>Портфель</Table.Th>
                        <Table.Th w={190}>Запущен</Table.Th>
                        <Table.Th w={200}>Решение</Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {rows.map((row) => (
                        <Table.Tr
                          key={row.run_id}
                          className="clickable-row"
                          onClick={() => navigate(`/runs/${row.run_id}`)}
                        >
                          <Table.Td>
                            <Text size="sm" fw={500} lineClamp={2}>
                              {row.event_text}
                            </Text>
                          </Table.Td>
                          <Table.Td>
                            <StatusBadge state={row.status} />
                          </Table.Td>
                          <Table.Td>
                            <PortfolioCell id={row.portfolio_id} name={nameOf(row.portfolio_id)} />
                          </Table.Td>
                          <Table.Td>
                            <Text size="sm">{timestamp(row.created_at)}</Text>
                            {row.created_by && (
                              <Text size="xs" c="dimmed">
                                {row.created_by}
                              </Text>
                            )}
                          </Table.Td>
                          <Table.Td>
                            {row.approved_by ? (
                              <>
                                <Text size="sm">Утвердил: {approver(row.approved_by)}</Text>
                                <Text size="xs" c="dimmed">
                                  {timestamp(row.approved_at)}
                                </Text>
                              </>
                            ) : (
                              <Text size="sm" c="dimmed">
                                —
                              </Text>
                            )}
                          </Table.Td>
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                </Table.ScrollContainer>
              )}
            </Paper>
          </Stack>
        </>
      )}
    </Stack>
  );
}
