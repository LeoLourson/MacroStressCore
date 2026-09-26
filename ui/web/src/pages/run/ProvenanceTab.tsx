import { Center, Collapse, Loader, Paper, Stack, Table, Text, TextInput } from '@mantine/core';
import { IconSearch } from '@tabler/icons-react';
import { Fragment, useMemo, useState } from 'react';
import { ErrorAlert } from '../../components/ErrorAlert';
import { OriginBody } from '../../components/Provenance';
import { describePath, number } from '../../lib/format';
import { howObtained } from '../../lib/origin';
import type { RunTabProps } from './RunPage';
import { useOrigins } from './useOrigins';

/** Every number of the report: how it was reached and what data it rests on. */
export function ProvenanceTab({ status, artifacts }: RunTabProps) {
  const { trace } = useOrigins(status);
  const [search, setSearch] = useState('');
  const [open, setOpen] = useState<string | null>(null);

  const rows = useMemo(
    () =>
      (trace.data?.numbers ?? []).map((n) => ({
        entry: n,
        what: describePath(n.metric_path, {
          names: artifacts.position_names,
          types: Object.fromEntries((artifacts.results ?? []).map((r) => [r.position_id, r.instrument_type])),
        }),
        value: number(n.value, n.number_ref.rounding),
        how: howObtained(n.metric_path, artifacts),
      })),
    [trace.data, artifacts],
  );
  const needle = search.trim().toLowerCase();
  const shown = needle ? rows.filter((r) => r.what.toLowerCase().includes(needle)) : rows;

  if (trace.error) return <ErrorAlert error={trace.error} />;
  if (trace.isPending) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }
  if (!trace.data) return <Text c="dimmed">Происхождение чисел появится вместе с отчётом.</Text>;

  return (
    <Stack gap="md">
      <Text size="sm" c="dimmed" maw="80ch">
        Все числа текста отчёта. Нажмите на строку: откроются сценарий, фрагменты события и данные позиции, на которых
        число основано, с автором и датой каждого допущения.
      </Text>
      <TextInput
        placeholder="Поиск: позиция, показатель, срез"
        leftSection={<IconSearch size={16} />}
        value={search}
        onChange={(e) => setSearch(e.currentTarget.value)}
        maw={420}
        aria-label="Поиск по числам отчёта"
      />
      <Paper>
        <Table.ScrollContainer minWidth={760}>
          <Table fz="sm" verticalSpacing="xs" highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th className="num-right" w={120}>
                  Число
                </Table.Th>
                <Table.Th w="38%">Что это</Table.Th>
                <Table.Th>Как получено</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {shown.map((row) => {
                const expanded = open === row.entry.metric_path;
                const toggle = () => setOpen(expanded ? null : row.entry.metric_path);
                return (
                  <Fragment key={row.entry.metric_path}>
                    <Table.Tr
                      className="clickable-row"
                      tabIndex={0}
                      aria-expanded={expanded}
                      onClick={toggle}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          toggle();
                        }
                      }}
                    >
                      <Table.Td className="num-right" fw={600}>
                        {row.value}
                      </Table.Td>
                      <Table.Td>{row.what}</Table.Td>
                      <Table.Td c="dimmed">{row.how}</Table.Td>
                    </Table.Tr>
                    <Table.Tr style={{ display: expanded ? undefined : 'none' }}>
                      <Table.Td colSpan={3} bg="gray.0">
                        <Collapse in={expanded}>
                          <Stack py={4} maw="90ch">
                            {expanded && <OriginBody entry={row.entry} withHow={false} />}
                          </Stack>
                        </Collapse>
                      </Table.Td>
                    </Table.Tr>
                  </Fragment>
                );
              })}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Paper>
    </Stack>
  );
}
