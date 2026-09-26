import { Anchor, Badge, Button, Center, Collapse, Group, Loader, Modal, Paper, Stack, Table, Text, Title } from '@mantine/core';
import { IconCopy, IconPlayerPlay, IconPlus, IconTrash } from '@tabler/icons-react';
import { Fragment, useState } from 'react';
import { Link, Navigate } from 'react-router';
import { useDeletePortfolio, usePortfolio, usePortfolios } from '../api/queries';
import type { PortfolioRow } from '../api/types';
import { canRun, useSession } from '../auth/session';
import { ErrorAlert } from '../components/ErrorAlert';
import { day, plural, timestamp, typeName } from '../lib/format';

function Composition({ portfolioId }: { portfolioId: string }) {
  const bundle = usePortfolio(portfolioId, true);
  if (bundle.error) return <ErrorAlert error={bundle.error} />;
  if (!bundle.data) return <Loader size="sm" />;
  const { instruments, positions, parties, portfolio } = bundle.data;
  const byId = Object.fromEntries(instruments.map((i) => [i.instrument_id, i]));
  const okved = Object.fromEntries(parties.map((p) => [p.party_id, p.okved]));
  return (
    <Stack gap={4}>
      <Text size="sm" c="dimmed">
        {plural(positions.length, 'позиция', 'позиции', 'позиций')}; базовая валюта {portfolio.base_currency}
        {portfolio.as_of ? `; дата оценки ${day(portfolio.as_of)}` : ''}
        {portfolio.snapshot_id ? `; данные — снимок ${portfolio.snapshot_id}` : ''}
      </Text>
      <Table withTableBorder fz="sm">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Позиция</Table.Th>
            <Table.Th>Тип</Table.Th>
            <Table.Th>Валюта</Table.Th>
            <Table.Th>ОКВЭД эмитента</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {positions.map((position) => {
            const instrument = byId[position.instrument_id];
            return (
              <Table.Tr key={position.position_id}>
                <Table.Td>
                  {position.position_id}
                  <Text size="xs" c="dimmed">
                    {instrument?.name}
                  </Text>
                </Table.Td>
                <Table.Td>{typeName(instrument?.instrument_type)}</Table.Td>
                <Table.Td>{instrument?.currency}</Table.Td>
                <Table.Td>{(instrument?.issuer_id && okved[instrument.issuer_id]) || '—'}</Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}

/** The portfolios a stress test can run on: the built-in demo set and the analyst's own. */
export function Portfolios() {
  const { me, mode } = useSession();
  const portfolios = usePortfolios(true);
  const demo = mode === 'demo';
  const remove = useDeletePortfolio();
  const [open, setOpen] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<PortfolioRow | null>(null);

  if (!canRun(me)) return <Navigate to="/" replace />;
  return (
    <Stack gap="lg">
      <Group justify="space-between">
        <Stack gap={2}>
          <Title order={2}>Портфели</Title>
          <Text size="sm" c="dimmed" maw="80ch">
            {demo
              ? 'Встроенные демо-портфели и портфели, собранные в редакторе. Свой портфель хранится семь дней; каждое его число записано как допущение аналитика с автором и датой.'
              : 'Портфели банка, загруженные из его систем (ops/load_portfolio.py). Свой портфель для проверки можно собрать в демо-контуре.'}
          </Text>
        </Stack>
        {demo && (
          <Button component={Link} to="/portfolios/new" leftSection={<IconPlus size={16} />}>
            Новый портфель
          </Button>
        )}
      </Group>
      {portfolios.error && <ErrorAlert error={portfolios.error} />}
      {!portfolios.data ? (
        <Center py="xl">
          <Loader />
        </Center>
      ) : (
        <Paper>
          <Table verticalSpacing="sm" horizontalSpacing="md">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Портфель</Table.Th>
                <Table.Th>Вид</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {portfolios.data.map((p) => (
                <Fragment key={p.portfolio_id}>
                  <Table.Tr>
                    <Table.Td>
                      <Anchor component="button" type="button" onClick={() => setOpen(open === p.portfolio_id ? null : p.portfolio_id)}>
                        {p.name && p.name !== p.portfolio_id ? p.name : p.portfolio_id}
                      </Anchor>
                      <Text size="xs" c="dimmed" ff="monospace">
                        {p.portfolio_id}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      {!demo ? (
                        <Badge variant="light" color="gray" tt="none" fw={500}>
                          Портфель банка
                        </Badge>
                      ) : p.builtin ? (
                        <Badge variant="light" color="gray" tt="none" fw={500}>
                          Демо-портфель
                        </Badge>
                      ) : (
                        <Stack gap={0}>
                          <Badge variant="light" color="steel" tt="none" fw={500} w="fit-content">
                            Свой
                          </Badge>
                          {p.expires_at && (
                            <Text size="xs" c="dimmed">
                              хранится до {timestamp(p.expires_at)}
                            </Text>
                          )}
                        </Stack>
                      )}
                    </Table.Td>
                    <Table.Td>
                      <Group gap="xs" justify="flex-end" wrap="nowrap">
                        <Button
                          size="xs"
                          component={Link}
                          to={`/new?portfolio=${encodeURIComponent(p.portfolio_id)}`}
                          leftSection={<IconPlayerPlay size={14} />}
                        >
                          Стресс-тест
                        </Button>
                        {demo && (
                          <Button
                            size="xs"
                            variant="default"
                            component={Link}
                            to={`/portfolios/new?from=${encodeURIComponent(p.portfolio_id)}`}
                            leftSection={<IconCopy size={14} />}
                          >
                            Скопировать и изменить
                          </Button>
                        )}
                        {demo && !p.builtin && (
                          <Button
                            size="xs"
                            variant="subtle"
                            color="gray"
                            leftSection={<IconTrash size={14} />}
                            onClick={() => setDeleting(p)}
                          >
                            Удалить
                          </Button>
                        )}
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                  <Table.Tr style={{ display: open === p.portfolio_id ? undefined : 'none' }}>
                    <Table.Td colSpan={3} bg="gray.0">
                      <Collapse in={open === p.portfolio_id}>
                        {open === p.portfolio_id && <Composition portfolioId={p.portfolio_id} />}
                      </Collapse>
                    </Table.Td>
                  </Table.Tr>
                </Fragment>
              ))}
            </Table.Tbody>
          </Table>
        </Paper>
      )}
      <Modal opened={!!deleting} onClose={() => setDeleting(null)} title="Удалить портфель?" centered>
        <Stack>
          <Text size="sm">
            Портфель «{deleting?.name ?? deleting?.portfolio_id}» будет удалён. Стресс-тесты, уже проведённые на нём,
            сохранятся.
          </Text>
          {remove.error && <ErrorAlert error={remove.error} />}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setDeleting(null)}>
              Оставить
            </Button>
            <Button
              color="gray"
              loading={remove.isPending}
              onClick={() =>
                deleting && remove.mutate(deleting.portfolio_id, { onSuccess: () => setDeleting(null) })
              }
            >
              Удалить
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
