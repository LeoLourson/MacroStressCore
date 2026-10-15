import { Code, Group, Stack, Table, Text } from '@mantine/core';
import { PageSection } from '../../../components/Page';
import { useMemo } from 'react';
import { SourceInputs } from '../../../components/Provenance';
import { day, plural } from '../../../lib/format';
import { bySource, positionInputs, sourceMeta } from '../../../lib/sources';
import { pluginNotes } from '../../../plugins';
import type { RunTabProps } from '../RunPage';

const SNAPSHOT_KINDS: Record<string, string> = { demo: 'демо-данные', production: 'рабочие данные' };

/**
 * What the stress test rests on besides the event text: the data snapshot and, source by
 * source, who stands behind the data, on what date, and which inputs of which position it
 * gave. Where a single number of the report comes from opens at the number itself.
 */
export function SourcesTab({ artifacts }: RunTabProps) {
  const sources = useMemo(() => {
    const contexts = new Map((artifacts.positions ?? []).map((c) => [c.position.position_id, c]));
    const results = new Map((artifacts.results ?? []).map((r) => [r.position_id, r]));
    const ids = [...new Set([...contexts.keys(), ...results.keys()])];
    return bySource(
      ids.flatMap((id) => positionInputs(contexts.get(id), results.get(id))),
      artifacts.position_names,
    );
  }, [artifacts]);
  const snapshot = artifacts.snapshot;
  const Notes = pluginNotes();

  return (
    <Stack gap="lg">
      {snapshot && (
        <PageSection
          title="Снимок данных"
          hint="На каких данных построен расчёт: кто и на какую дату их внёс и какие показатели каких позиций из них взяты. Основания сценария — на вкладке «Сценарий и граф»; откуда конкретное число отчёта, видно по клику на число."
        >
          <Stack gap={4}>
            <Text fw={500}>{snapshot.label}</Text>
            <Group gap={4}>
              <Text size="sm" c="dimmed">
                на {day(snapshot.as_of)} · {SNAPSHOT_KINDS[snapshot.kind] ?? snapshot.kind} · контрольная сумма
              </Text>
              <Code fz="xs">{snapshot.sha256.slice(0, 12)}</Code>
            </Group>
          </Stack>
        </PageSection>
      )}
      {sources.length === 0 && (
        <Text size="sm" c="dimmed">
          У данных позиций не указаны источники.
        </Text>
      )}
      {sources.map((source) => (
        <PageSection
          key={source.key}
          flush
          title={source.name}
          aside={`${sourceMeta(source)} · ${plural(source.count, 'значение', 'значения', 'значений')}`}
        >
            <Table.ScrollContainer minWidth={560}>
              <Table verticalSpacing="sm">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th w="28%">Позиция</Table.Th>
                    <Table.Th>Что взято</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {source.positions.map((position) => (
                    <Table.Tr key={position.positionId}>
                      <Table.Td valign="top">
                        <Text size="sm" fw={500}>
                          {position.title}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <SourceInputs source={{ ...source, positions: [position] }} meta={false} />
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
        </PageSection>
      ))}
      {/* A setting in force the money figures rest on, such as the PD calibration. */}
      {Notes.map((Note, i) => (
        <Note key={i} artifacts={artifacts} />
      ))}
    </Stack>
  );
}
