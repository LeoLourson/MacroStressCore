import { Alert, Box, Code, Group, List, SimpleGrid, Stack, Table, Text, Title } from '@mantine/core';
import { IconAlertTriangle, IconInfoCircle } from '@tabler/icons-react';
import { sliceSpec } from '../../../api/catalog';
import { useReport } from '../../../api/queries';
import type { Artifacts, Report, SliceResult } from '../../../api/types';
import { TracedNumber } from '../../../components/Provenance';
import { ResultStatus } from '../../../components/RiskModel';
import { ResultSummary } from '../../../components/ResultSummary';
import { PageSection, Subsection } from '../../../components/Page';
import { capitalize, describePath, formatter, number, pathValue, percent, positionTitle, slicePath } from '../../../lib/format';
import { ACTIONS, RESULT_STATUS, RULES, flagList, label, translateFlags } from '../../../lib/labels';
import type { Entries } from '../../../lib/provenance';
import { hasReport } from '../../../lib/stages';
import { agentComponent, pluginNotes } from '../../../plugins';
import type { RunTabProps } from '../RunPage';
import { glossary } from '../ReportText';
import { useOrigins } from '../useOrigins';

function Slice({ item, artifacts, entries, several }: { item: SliceResult; artifacts: Artifacts; entries: Entries; several: boolean }) {
  const spec = sliceSpec(item.slice_id);
  const names = artifacts.position_names;
  const format = formatter(item.unit);
  const q = item.loss_quantiles;
  const es = item.expected_shortfall_95;
  const sum95 = item.sum_of_individual_p95;
  const contributions = [...item.contributions].sort(
    (a, b) => b.expected_shortfall_contribution - a.expected_shortfall_contribution,
  );
  const notes = flagList(item.flags.filter((f) => !f.startsWith('included_by_rule:') && !f.startsWith('inclusion_rule:')));
  return (
    <PageSection
      title={spec?.label ?? item.slice_id}
      // Only several slices raise the question whether they add up.
      hint={[spec?.description, several && 'Срезы считаются отдельно на одних и тех же сценариях: у каждого своя мера и база покрытия, между собой они не складываются.'].filter(Boolean).join(' ') || undefined}
      aside={item.status !== 'ok' && <ResultStatus status={item.status} />}
    >
        {q ? (
          <ResultSummary item={item} artifacts={artifacts} entries={entries} />
        ) : (
          <Alert color="orange" icon={<IconAlertTriangle />}>
            Распределение среза не построено: ни одна позиция не вошла в итог. Причины — ниже.
          </Alert>
        )}
        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="lg">
          <Stack gap="xs">
            <Text size="sm">
              Расчётом охвачено{' '}
              <b>
                <TracedNumber entry={entries.get(slicePath(item.slice_id, 'covered_percent'))}>
                  {percent(item.coverage.covered_share)}
                </TracedNumber>
              </b>{' '}
              {(spec?.exposure_label ?? 'размера позиций').toLowerCase()} (допустимо не меньше{' '}
              {percent(1 - item.coverage.limit, 0)}).
            </Text>
            {item.coverage.unknown_exposure.length > 0 && (
              <Text size="sm">
                Размер не измерен: {item.coverage.unknown_exposure.map((id) => positionTitle(id, names)).join(', ')} — итог
                неполный.
              </Text>
            )}
            {item.coverage.portfolio_share != null && (
              <Text size="sm">
                Событие затронуло{' '}
                <b>
                  <TracedNumber entry={entries.get(slicePath(item.slice_id, 'portfolio_percent'))}>
                    {percent(item.coverage.portfolio_share)}
                  </TracedNumber>
                </b>{' '}
                {(spec?.exposure_label ?? 'размера позиций').toLowerCase()} портфеля.
              </Text>
            )}
            <Text size="sm">
              Концентрация — индекс Херфиндаля <b>{number(item.herfindahl, 3)}</b>
              {item.coverage.portfolio_share != null ? ' по всему портфелю' : ' по затронутым позициям'}.
            </Text>
            {sum95 != null && q && item.included.length > 1 && sum95 > q.p95 * 1.005 && (
              <Text size="sm">
                Сумма P95 по позициям — <b>{format(sum95)}</b>, P95 среза — <b>{format(q.p95)}</b>: худшие сценарии разных
                позиций не совпадают полностью, поэтому риск среза меньше суммы рисков по отдельности.
              </Text>
            )}
            {notes.length > 0 && (
              <Text size="xs" c="dimmed">
                {capitalize(notes.join('; '))}.
              </Text>
            )}
          </Stack>
          {contributions.length > 0 && es != null && es > 0 && (
            <Subsection title="Кто формирует хвост потерь" hint="Доля позиции в средних потерях худших 5 % сценариев (ES95).">
              <Stack gap={6}>
                {contributions.map((c) => {
                  const share = c.expected_shortfall_contribution / es;
                  return (
                    <Group key={c.position_id} gap="sm" wrap="nowrap">
                      <Text size="sm" w={220} lineClamp={2}>
                        {positionTitle(c.position_id, names)}
                      </Text>
                      <Box style={{ flex: 1 }} h={8} bg="gray.1">
                        <Box h={8} bg="steel.5" w={`${Math.max(0, Math.min(1, share)) * 100}%`} />
                      </Box>
                      <Text size="sm" w={70} className="num-right">
                        {percent(share)}
                      </Text>
                    </Group>
                  );
                })}
              </Stack>
            </Subsection>
          )}
        </SimpleGrid>
        {item.excluded.length > 0 && (
          <Alert color="orange" icon={<IconAlertTriangle />} title="Не вошли в итог среза">
            <List size="sm" spacing={4}>
              {item.excluded.map((e) => (
                <List.Item key={e.position_id}>
                  {positionTitle(e.position_id, names)} — {label(RESULT_STATUS, e.status)}
                  {e.reason ? `: ${translateFlags(e.reason)}` : ''}
                </List.Item>
              ))}
            </List>
          </Alert>
        )}
    </PageSection>
  );
}

function Recommendations({ report, artifacts }: { report: Report; artifacts: Artifacts }) {
  const names = artifacts.position_names;
  const types = Object.fromEntries((artifacts.results ?? []).map((r) => [r.position_id, r.instrument_type]));
  const words = glossary(artifacts);
  const grouped = new Map<string, Report['recommendations']>();
  for (const rec of report.recommendations ?? []) {
    grouped.set(rec.position_id, [...(grouped.get(rec.position_id) ?? []), rec]);
  }
  return (
    <PageSection title="Рекомендации" hint="Действия, которые правила назначили позициям по их показателям." flush={grouped.size > 0}>
      {grouped.size === 0 && (
        <Text size="sm" c="dimmed">
          Правила не назначили действий ни одной позиции.
        </Text>
      )}
      {grouped.size > 0 && (
        <Table verticalSpacing="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Позиция</Table.Th>
              <Table.Th>Действие</Table.Th>
              <Table.Th>Основание</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {[...grouped.entries()]
              .sort(([a], [b]) => a.localeCompare(b))
              .flatMap(([positionId, items]) => {
                const byRule = new Map<string, typeof items>();
                for (const rec of items) byRule.set(rec.rule_id, [...(byRule.get(rec.rule_id) ?? []), rec]);
                return [...byRule.entries()].map(([rule, recs], index) => {
                  const refs = [...new Set(recs.flatMap((r) => r.metric_refs))];
                  const grounds = refs
                    .map((ref) => `${describePath(ref, { names, types, owner: false, words })} = ${pathValue(artifacts.metric_tree, ref)}`)
                    .join('; ');
                  return (
                    <Table.Tr key={`${positionId}|${rule}`}>
                      <Table.Td fw={600}>{index === 0 ? positionTitle(positionId, names) : ''}</Table.Td>
                      <Table.Td>{capitalize(recs.map((r) => label(ACTIONS, r.action)).join(' и '))}</Table.Td>
                      <Table.Td>
                        <Text size="sm">{capitalize(label(RULES, rule))}.</Text>
                        {grounds && (
                          <Text size="xs" c="dimmed">
                            {grounds}
                            {grounds.endsWith('.') ? '' : '.'}
                          </Text>
                        )}
                      </Table.Td>
                    </Table.Tr>
                  );
                });
              })}
          </Table.Tbody>
        </Table>
      )}
    </PageSection>
  );
}

/** An agent's output drawn as is: lists of lines as lists, anything else as JSON. */
function PlainOutput({ output }: { output: Record<string, unknown> }) {
  return (
    <>
      {Object.entries(output).map(([key, value]) =>
        Array.isArray(value) && value.every((v) => typeof v === 'string') ? (
          <List key={key} size="sm" spacing={4}>
            {(value as string[]).map((line) => (
              <List.Item key={line}>{line}</List.Item>
            ))}
          </List>
        ) : (
          <Code key={key} block fz="xs">
            {key}: {JSON.stringify(value, null, 1)}
          </Code>
        ),
      )}
    </>
  );
}

/**
 * What agent plugins added to the run, each in its own namespace; never part of the numbers.
 * A UI plugin may draw its agents' outputs (UiPlugin.agents); a failed agent is shown as such.
 */
export function Extensions({ artifacts }: { artifacts: Artifacts }) {
  const items = Object.entries(artifacts.extensions ?? {});
  if (!items.length) return null;
  // The run's workflow names its plugin agents in its stages; the catalog adds the rest.
  const labels: Record<string, string> = Object.fromEntries([
    ...(artifacts.workflow?.stages ?? []).flatMap((stage) => stage.nodes.map((n) => [n.node, n.label])),
    ...(artifacts.workflow?.agents ?? []).map((a) => [a.agent_id, a.label]),
  ]);
  return (
    <PageSection
      title="Дополнительные агенты"
      hint="Агенты плагинов пишут только в своё пространство: их выводы не меняют сценарий, расчёты и отчёт."
    >
      {items.map(([agentId, output]) => {
        const View = output.failed === true ? null : agentComponent(agentId);
        return (
          <Stack key={agentId} gap={4}>
            <Group gap="xs">
              <Title order={4}>{labels[agentId] ?? agentId}</Title>
              {output.failed === true && (
                <Group gap={4}>
                  <IconAlertTriangle size={14} />
                  <Text size="sm">агент не завершился</Text>
                </Group>
              )}
            </Group>
            {View ? <View output={output} artifacts={artifacts} /> : <PlainOutput output={output} />}
          </Stack>
        );
      })}
    </PageSection>
  );
}

export function PortfolioTab({ status, artifacts }: RunTabProps) {
  const portfolio = artifacts.portfolio;
  const report = useReport(status, hasReport(status));
  const { entries } = useOrigins(status);
  if (!portfolio) return <Text c="dimmed">Итоги по срезам портфеля появятся после расчёта по позициям.</Text>;
  const slices = Object.values(portfolio.slices).sort((a, b) => a.slice_id.localeCompare(b.slice_id));
  const Notes = pluginNotes();

  return (
    <Stack gap="lg">
      {slices.map((item) => (
        <Slice key={item.slice_id} item={item} artifacts={artifacts} entries={entries} several={slices.length > 1} />
      ))}
      {portfolio.not_aggregated.length > 0 && (
        <Alert color="gray" icon={<IconInfoCircle />} title="Позиции вне итогов срезов">
          <List size="sm" spacing={4}>
            {portfolio.not_aggregated.map((e) => (
              <List.Item key={e.position_id}>
                {positionTitle(e.position_id, artifacts.position_names)} — {translateFlags(e.reason)}
              </List.Item>
            ))}
          </List>
        </Alert>
      )}
      {report.data ? (
        <Recommendations report={report.data} artifacts={artifacts} />
      ) : (
        <Text size="sm" c="dimmed">
          Рекомендации появятся вместе с отчётом.
        </Text>
      )}
      <Extensions artifacts={artifacts} />
      {Notes.map((Note, i) => (
        <Note key={i} artifacts={artifacts} />
      ))}
    </Stack>
  );
}
