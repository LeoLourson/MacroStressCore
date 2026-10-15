import {
  Button,
  Center,
  Group,
  Loader,
  Modal,
  Paper,
  SegmentedControl,
  Stack,
  Table,
  Text,
  TextInput,
} from '@mantine/core';
import { IconArrowRight, IconPlus, IconSearch, IconTrash } from '@tabler/icons-react';
import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { useDeleteRun, usePortfolios, useRuns } from '../api/queries';
import type { Me, RunRow } from '../api/types';
import { canApprove, canFixGraph, canRun, useSession } from '../auth/session';
import { ErrorAlert } from '../components/ErrorAlert';
import { PageHeader } from '../components/Page';
import { StatusBadge } from '../components/StatusBadge';
import { approver, timestamp } from '../lib/format';
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

export function RunsList() {
  const { me, mode } = useSession();
  const navigate = useNavigate();
  const runs = useRuns();
  const remove = useDeleteRun();
  const [deleting, setDeleting] = useState<RunRow | null>(null);
  // Demo runs only: a production run stays as the bank's record.
  const canDelete = mode === 'demo' && canRun(me);
  const [filter, setFilter] = useState<Filter>('all');
  const [search, setSearch] = useState('');
  const nameOf = usePortfolioName();

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const found = (runs.data ?? []).filter(
      (row) =>
        matches(row, filter) &&
        (!needle ||
          row.event_text.toLowerCase().includes(needle) ||
          row.portfolio_id.toLowerCase().includes(needle) ||
          (nameOf(row.portfolio_id) ?? '').toLowerCase().includes(needle)),
    );
    // What waits for this person comes first; the order within each part stays the list's.
    return [...found.filter((row) => waitsFor(row, me)), ...found.filter((row) => !waitsFor(row, me))];
  }, [runs.data, filter, search, nameOf, me]);

  return (
    <Stack gap="lg">
      <PageHeader
        title="Стресс-тесты"
        hint="Как одно событие повлияет на портфель: граф влияния, расчёт позиций, отчёт."
        actions={
          canRun(me) && (
            <Button component={Link} to="/new" leftSection={<IconPlus size={16} />}>
              Новый стресс-тест
            </Button>
          )
        }
      />

      {runs.error && <ErrorAlert error={runs.error} />}
      {runs.isPending ? (
        <Center py="xl">
          <Loader />
        </Center>
      ) : (
        <>
          {/* The filters belong to the table: they are the head of its card, on the card's padding. */}
            <Paper className="flush" style={{ minWidth: 0 }}>
              <Group justify="space-between" p="lg" pb="sm" gap="sm">
                <SegmentedControl value={filter} onChange={(v) => setFilter(v as Filter)} data={FILTERS} />
                <TextInput
                  placeholder="Поиск по событию или портфелю"
                  leftSection={<IconSearch size={16} />}
                  value={search}
                  onChange={(e) => setSearch(e.currentTarget.value)}
                  w={{ base: '100%', sm: 320 }}
                />
              </Group>
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
                        <Table.Th w={240}>Решение</Table.Th>
                        {canDelete && <Table.Th w={130} />}
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
                            {waitsFor(row, me) ? (
                              <Button
                                size="xs"
                                variant="light"
                                rightSection={<IconArrowRight size={14} />}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  navigate(`/runs/${row.run_id}`);
                                }}
                              >
                                {waitsFor(row, me)}
                              </Button>
                            ) : row.approved_by ? (
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
                          {canDelete && (
                            <Table.Td>
                              {!ACTIVE.includes(row.status) && (
                                <Button
                                  size="xs"
                                  variant="subtle"
                                  color="gray"
                                  leftSection={<IconTrash size={14} />}
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    remove.reset();
                                    setDeleting(row);
                                  }}
                                >
                                  Удалить
                                </Button>
                              )}
                            </Table.Td>
                          )}
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                </Table.ScrollContainer>
              )}
            </Paper>
        </>
      )}
      <Modal opened={!!deleting} onClose={() => setDeleting(null)} title="Удалить стресс-тест?" centered withCloseButton={false}>
        <Stack>
          <Text size="sm" lineClamp={4}>
            Стресс-тест «{deleting?.event_text}» будет удалён вместе с графом, расчётом, отчётом и вопросами к нему.
            Портфель останется.
          </Text>
          {remove.error && <ErrorAlert error={remove.error} />}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setDeleting(null)}>
              Оставить
            </Button>
            <Button
              color="gray"
              loading={remove.isPending}
              onClick={() => deleting && remove.mutate(deleting.run_id, { onSuccess: () => setDeleting(null) })}
            >
              Удалить
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
