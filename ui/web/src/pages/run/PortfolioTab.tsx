import { Alert, Box, Code, Group, List, Paper, SimpleGrid, Stack, Text, Title } from '@mantine/core';
import { IconAlertTriangle, IconInfoCircle } from '@tabler/icons-react';
import { sliceSpec } from '../../api/catalog';
import { useReport } from '../../api/queries';
import type { Artifacts, Report, SliceResult } from '../../api/types';
import { IntervalBar, IntervalLegend, scaleOf } from '../../components/Interval';
import { TracedNumber } from '../../components/Provenance';
import { ResultStatus } from '../../components/RiskModel';
import { Term } from '../../components/Term';
import { bareValue, capitalize, describePath, formatter, number, pathValue, percent, positionTitle, slicePath } from '../../lib/format';
import { ACTIONS, RESULT_STATUS, RULES, flagList, label, translateFlags } from '../../lib/labels';
import type { Entries } from '../../lib/provenance';
import { hasReport } from '../../lib/stages';
import { agentComponent, baselineOf, pluginNotes } from '../../plugins';
import type { RunTabProps } from './RunPage';
import { glossary } from './ReportText';
import { useOrigins } from './useOrigins';

function Slice({ item, artifacts, entries }: { item: SliceResult; artifacts: Artifacts; entries: Entries }) {
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
  // The level before the event: the sum of the included positions' levels, when each is known.
  const levels = item.included.map((id) => {
    const result = artifacts.results?.find((r) => r.position_id === id);
    return result ? baselineOf(result, item.measure) : null;
  });
  const base = levels.length && levels.every((v) => v != null) ? levels.reduce((a: number, v) => a + v!, 0) : null;
  const shift = base ?? 0;
  const scale = q ? scaleOf([q.p05, q.p95, sum95, es].map((v) => (v == null ? v : v + shift)).concat(base)) : null;
  return (
    <Paper p="lg">
      <Stack gap="md">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Title order={4}>{spec?.label ?? item.slice_id}</Title>
            <Text size="sm" c="dimmed" maw="70ch">
              {spec?.description ||
                'Потери позиций среза суммируются внутри каждого общего сценария; квантили берутся от суммы.'}
            </Text>
          </Stack>
          {item.status !== 'ok' && <ResultStatus status={item.status} />}
        </Group>
        {q ? (
          <Stack gap="xs">
            <Group gap="xl" align="flex-end">
              <Stack gap={0}>
                <Text size="xs" c="dimmed">
                  {spec?.measure_label ?? 'Потери'}, медиана (P50)
                </Text>
                <Text fz={28} fw={700} className="num" lh={1.2}>
                  <TracedNumber entry={entries.get(slicePath(item.slice_id, 'loss_quantiles', 'p50'))}>
                    {format(q.p50)}
                  </TracedNumber>
                </Text>
              </Stack>
              <Stack gap={0}>
                <Text size="xs" c="dimmed">
                  <Term name="P5–P95">P5 … P95</Term>
                </Text>
                <Text size="lg" className="num">
                  <TracedNumber entry={entries.get(slicePath(item.slice_id, 'loss_quantiles', 'p05'))}>
                    {format(q.p05)}
                  </TracedNumber>{' '}
                  …{' '}
                  <TracedNumber entry={entries.get(slicePath(item.slice_id, 'loss_quantiles', 'p95'))}>
                    {format(q.p95)}
                  </TracedNumber>
                </Text>
              </Stack>
              {es != null && (
                <Stack gap={0}>
                  <Text size="xs" c="dimmed">
                    <Term name="ES95">Средние потери в худших 5 % (ES95)</Term>
                  </Text>
                  <Text size="lg" className="num">
                    <TracedNumber entry={entries.get(slicePath(item.slice_id, 'loss_quantiles', 'es95'))}>
                      {format(es)}
                    </TracedNumber>
                  </Text>
                </Stack>
              )}
            </Group>
            {base != null && (
              <Text size="sm">
                До события — <b>{format(base)}</b>, после события по медиане — <b>{format(base + q.p50)}</b> (P5–P95:{' '}
                {bareValue(base + q.p05, item.unit)} … {format(base + q.p95)}).
              </Text>
            )}
            <Stack gap={2} mt={4}>
              <IntervalBar
                p05={q.p05 + shift}
                p50={q.p50 + shift}
                p95={q.p95 + shift}
                base={base}
                tail={es == null ? null : es + shift}
                scale={scale!}
                width="100%"
              />
              <Group justify="space-between">
                <Text size="xs" c="dark.3" className="num">
                  {format(scale!.lo)}
                </Text>
                <Text size="xs" c="dark.3" className="num">
                  {format(scale!.hi)}
                </Text>
              </Group>
            </Stack>
            <IntervalLegend
              base={base != null}
              tail={es != null}
              note={base == null ? 'Отрицательные значения — прирост, положительные — потери.' : undefined}
            />
          </Stack>
        ) : (
          <Alert color="orange" variant="light" icon={<IconAlertTriangle />}>
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
              <Text size="xs" c="dark.3">
                {capitalize(notes.join('; '))}.
              </Text>
            )}
          </Stack>
          {contributions.length > 0 && es != null && es > 0 && (
            <Stack gap="xs">
              <Text size="sm" fw={600}>
                Кто формирует хвост потерь
              </Text>
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
            </Stack>
          )}
        </SimpleGrid>
        {item.excluded.length > 0 && (
          <Alert color="orange" variant="light" icon={<IconAlertTriangle />} title="Не вошли в итог среза">
            <List size="sm" spacing={2}>
              {item.excluded.map((e) => (
                <List.Item key={e.position_id}>
                  {positionTitle(e.position_id, names)} — {label(RESULT_STATUS, e.status)}
                  {e.reason ? `: ${translateFlags(e.reason)}` : ''}
                </List.Item>
              ))}
            </List>
          </Alert>
        )}
      </Stack>
    </Paper>
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
    <Stack gap="xs">
      <Title order={4}>Рекомендации</Title>
      {grouped.size === 0 && (
        <Text size="sm" c="dimmed">
          Правила не назначили действий ни одной позиции.
        </Text>
      )}
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        {[...grouped.entries()]
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([positionId, items]) => {
            const byRule = new Map<string, typeof items>();
            for (const rec of items) byRule.set(rec.rule_id, [...(byRule.get(rec.rule_id) ?? []), rec]);
            return (
              <Paper key={positionId} p="md">
                <Stack gap="xs">
                  <Text fw={600}>{positionTitle(positionId, names)}</Text>
                  {[...byRule.entries()].map(([rule, recs]) => {
                    const refs = [...new Set(recs.flatMap((r) => r.metric_refs))];
                    const grounds = refs
                      .map((ref) => `${describePath(ref, { names, types, owner: false, words })} = ${pathValue(artifacts.metric_tree, ref)}`)
                      .join('; ');
                    return (
                      <Stack key={rule} gap={2}>
                        <Text size="sm" fw={500}>
                          {capitalize(recs.map((r) => label(ACTIONS, r.action)).join(' и '))}
                        </Text>
                        <Text size="xs" c="dimmed">
                          Почему: {label(RULES, rule)}.{grounds ? ` Основание: ${grounds}${grounds.endsWith('.') ? '' : '.'}` : ''}
                        </Text>
                      </Stack>
                    );
                  })}
                </Stack>
              </Paper>
            );
          })}
      </SimpleGrid>
    </Stack>
  );
}

/** An agent's output drawn as is: lists of lines as lists, anything else as JSON. */
function PlainOutput({ output }: { output: Record<string, unknown> }) {
  return (
    <>
      {Object.entries(output).map(([key, value]) =>
        Array.isArray(value) && value.every((v) => typeof v === 'string') ? (
          <List key={key} size="sm" spacing={2}>
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
    <Stack gap="xs">
      <Title order={4}>Дополнительные агенты</Title>
      <Text size="sm" c="dimmed" maw="80ch">
        Агенты плагинов пишут только в своё пространство: их выводы не меняют сценарий, расчёты и отчёт.
      </Text>
      {items.map(([agentId, output]) => {
        const View = output.failed === true ? null : agentComponent(agentId);
        return (
        <Paper key={agentId} p="md">
          <Stack gap={4}>
            <Group gap="xs">
              <Text fw={600}>{labels[agentId] ?? agentId}</Text>
              {output.failed === true && (
                <Group gap={4} c="dark.6">
                  <IconAlertTriangle size={14} />
                  <Text size="sm">агент не завершился</Text>
                </Group>
              )}
            </Group>
            {View ? <View output={output} artifacts={artifacts} /> : <PlainOutput output={output} />}
          </Stack>
        </Paper>
        );
      })}
    </Stack>
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
    <Stack gap="xl">
      {/* Only several slices raise the question whether they add up. */}
      {slices.length > 1 && (
        <Group gap="xs" c="dark.3">
          <IconInfoCircle size={16} />
          <Text size="sm" maw="80ch">
            <Term name="Срез портфеля">Срезы</Term> считаются отдельно на одних и тех же сценариях: у каждого своя мера и
            база покрытия, между собой они не складываются.
          </Text>
        </Group>
      )}
      {slices.map((item) => (
        <Slice key={item.slice_id} item={item} artifacts={artifacts} entries={entries} />
      ))}
      {portfolio.not_aggregated.length > 0 && (
        <Alert color="gray" variant="light" icon={<IconInfoCircle />} title="Позиции вне итогов срезов">
          <List size="sm" spacing={2}>
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
