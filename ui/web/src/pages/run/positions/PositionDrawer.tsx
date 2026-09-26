import { Alert, Drawer, List, Stack, Text, Title } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';
import { viewFor, type ResultView } from '../../../api/catalog';
import type { Artifacts, CalculationResult, PositionContext } from '../../../api/types';
import { ExecutionBadge } from '../../../components/RiskModel';
import { StandardView } from '../../../components/ResultBlocks';
import { instrumentLine, positionTitle } from '../../../lib/format';
import { DATA_QUALITY, flagList, label } from '../../../lib/labels';
import type { Entries } from '../../../lib/provenance';
import { viewComponent } from '../../../plugins';

/** A position whose plugin declares no view is shown with all its metrics and sources. */
function fallbackView(result: CalculationResult): ResultView {
  return {
    view_id: 'standard',
    instrument_types: [result.instrument_type],
    component: null,
    blocks: [
      { kind: 'metrics', title: 'Показатели', metric_ids: [], path: '', columns: [], hint: '' },
      { kind: 'sources', title: 'Источники данных', metric_ids: [], path: '', columns: [], hint: '' },
    ],
    summary_metrics: [],
    labels: {},
  };
}

/** Everything calculated for one position, opened in place from its row. */
export function PositionDrawer({
  result,
  context,
  artifacts,
  shocks,
  entries,
  onClose,
}: {
  result: CalculationResult | null;
  context: PositionContext | undefined;
  artifacts: Artifacts;
  shocks: Record<string, string>;
  entries: Entries;
  onClose: () => void;
}) {
  const names = artifacts.position_names;
  const view = result ? (viewFor(result.instrument_type) ?? fallbackView(result)) : null;
  // A UI plugin's view when one is installed; otherwise the blocks the plugin declares.
  const View = (view && viewComponent(view.component)) ?? StandardView;
  const notes = result ? flagList(result.flags, shocks) : [];
  const blocking = result?.diagnostics.filter((d) => d.severity === 'error') ?? [];
  const warnings = result?.diagnostics.filter((d) => d.severity === 'warning') ?? [];
  return (
    <Drawer
      opened={!!result}
      onClose={onClose}
      position="right"
      size="xl"
      title={result && <Title order={4}>{positionTitle(result.position_id, names)}</Title>}
    >
      {result && view && (
        <Stack gap="lg">
          <Stack gap={4}>
            <Text size="sm" c="dark.3">
              {instrumentLine(context)} · модель {result.model_id} {result.model_version} · качество данных{' '}
              {label(DATA_QUALITY, result.data_quality.level)}
            </Text>
            <ExecutionBadge result={result} />
          </Stack>
          {result.execution !== 'completed' ? (
            <Alert color="gray" variant="light" icon={<IconAlertTriangle />} title="Позиция не рассчитана">
              <List size="sm" spacing={2}>
                {[...blocking.map((d) => d.message || d.code), ...notes].map((line) => (
                  <List.Item key={line}>{line}</List.Item>
                ))}
              </List>
            </Alert>
          ) : (
            (notes.length > 0 || warnings.length > 0) && (
              <Text size="sm" c="dark.3">
                Особенности расчёта: {[...warnings.map((d) => d.message || d.code), ...notes].join('; ')}.
              </Text>
            )
          )}
          {result.execution === 'completed' && (
            <View result={result} context={context} view={view} artifacts={artifacts} entries={entries} shocks={shocks} />
          )}
          {result.limits?.note && (
            <Text size="xs" c="dark.3">
              Границы модели: {result.limits.note}
            </Text>
          )}
        </Stack>
      )}
    </Drawer>
  );
}
