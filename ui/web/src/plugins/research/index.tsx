// The research plugin's views of its agents' outputs: where a slice's tail loss concentrates
// (research.concentration) and how concentrated each slice is (research.digest, computed by
// the plugin's own MCP tool). The shares come from the positions' contributions to the
// slice's ES95 in this run; they are research notes and never enter the report.
import { Table, Text } from '@mantine/core';
import { sliceSpec } from '../../api/catalog';
import { number, percent, positionTitle } from '../../lib/format';
import type { AgentViewProps, UiPlugin } from '../sdk';
import meta from './plugin.json';

interface Note {
  slice_id: string;
  position_id: string;
  name: string;
  share_of_es95: number;
}

interface SliceDigest {
  slice_id: string;
  positions: number;
  top_share: number;
  herfindahl: number;
}

const sliceName = (sliceId: string) => sliceSpec(sliceId)?.label ?? sliceId;

function ConcentrationNotes({ output, artifacts }: AgentViewProps) {
  const notes = (output.notes ?? []) as Note[];
  if (!notes.length) return <Text size="sm">Существенной концентрации хвостового риска не найдено.</Text>;
  return (
    <>
      <Text size="xs" c="dimmed">
        Позиции с долей не меньше четверти в ES95 своего среза, по вкладам позиций этого прогона.
      </Text>
      <Table withTableBorder>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Срез</Table.Th>
            <Table.Th>Позиция</Table.Th>
            <Table.Th className="num-right">Доля в ES95</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {notes.map((note) => (
            <Table.Tr key={`${note.slice_id}:${note.position_id}`}>
              <Table.Td>{sliceName(note.slice_id)}</Table.Td>
              <Table.Td>{positionTitle(note.position_id, artifacts.position_names)}</Table.Td>
              <Table.Td className="num-right">{percent(note.share_of_es95, 0)}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </>
  );
}

function Digest({ output }: AgentViewProps) {
  const rows = (output.digest ?? []) as SliceDigest[];
  return (
    <>
      <Text size="xs" c="dimmed">
        Посчитано инструментом плагина mcp-research.notes по вкладам позиций в ES95 среза; вызов записан в журнал
        «Вызовы LLM и MCP».
      </Text>
      <Table withTableBorder>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Срез</Table.Th>
            <Table.Th className="num-right">Позиций</Table.Th>
            <Table.Th className="num-right">Наибольшая доля в ES95</Table.Th>
            <Table.Th className="num-right">Индекс Херфиндаля</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((row) => (
            <Table.Tr key={row.slice_id}>
              <Table.Td>{sliceName(row.slice_id)}</Table.Td>
              <Table.Td className="num-right">{row.positions}</Table.Td>
              <Table.Td className="num-right">{percent(row.top_share, 0)}</Table.Td>
              <Table.Td className="num-right">{number(row.herfindahl, 2)}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </>
  );
}

const plugin: UiPlugin = {
  ...meta,
  views: {},
  agents: { 'research.concentration': ConcentrationNotes, 'research.digest': Digest },
};

export default plugin;
