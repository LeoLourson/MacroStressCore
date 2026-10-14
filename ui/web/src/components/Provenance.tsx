import { Anchor, Blockquote, Group, Popover, ScrollArea, Stack, Text, UnstyledButton } from '@mantine/core';
import { IconInfoCircle } from '@tabler/icons-react';
import { createContext, useContext, type ReactNode } from 'react';
import { useSearchParams } from 'react-router';
import type { Artifacts, TraceNumber } from '../api/types';
import { describePath, nodeLabels, plural } from '../lib/format';
import { describeOrigin } from '../lib/origin';
import { sourceMeta, type SourceView } from '../lib/sources';

/** The run whose numbers are on screen: their origins are read against its artifacts. */
export const RunArtifacts = createContext<Artifacts | null>(null);

function Part({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Stack gap={4}>
      <Text size="xs" c="dimmed" fw={600}>
        {title}
      </Text>
      {children}
    </Stack>
  );
}

/** One source of data: whose and on what date (unless said above), and the inputs it gave by group. */
export function SourceInputs({ source, meta = true }: { source: SourceView; meta?: boolean }) {
  return (
    <Stack gap={4}>
      {meta && (
        <Text size="xs" c="dimmed">
          {sourceMeta(source)}
        </Text>
      )}
      {source.positions.map((position) => (
        <Stack key={position.positionId} gap={4}>
          {position.groups.map((group) => (
            <Text key={group.title} size="sm">
              <Text span c="dimmed" inherit>
                {group.title}:
              </Text>{' '}
              {group.items.join(', ')}
            </Text>
          ))}
          {position.unnamed > 0 && (
            <Text size="xs" c="dimmed">
              и ещё {plural(position.unnamed, 'показатель', 'показателя', 'показателей')} без названия
            </Text>
          )}
        </Stack>
      ))}
    </Stack>
  );
}

/** How the number was reached and what it rests on, in the analyst's terms. */
export function OriginBody({ entry }: { entry: TraceNumber }) {
  const artifacts = useContext(RunArtifacts);
  const [params, setParams] = useSearchParams();
  if (!artifacts) return null;
  const view = describeOrigin(entry, artifacts);
  const types = Object.fromEntries((artifacts.results ?? []).map((r) => [r.position_id, r.instrument_type]));
  const positionId = view.positionId;
  return (
    <Stack gap="sm">
      <Text size="xs" c="dimmed">
        {describePath(entry.metric_path, {
          names: artifacts.position_names,
          types,
          words: new Map(Object.entries(nodeLabels(artifacts.graph))),
        })}
      </Text>
      <Text size="sm">{view.how}</Text>
      {view.quotes.map((q) => (
        <Part key={q.where} title={q.where}>
          <Blockquote p="xs" fz="sm" color="gray" iconSize={0} styles={{ root: { borderWidth: 1 } }}>
            {q.text}
          </Blockquote>
        </Part>
      ))}
      {view.data.map((source) => (
        <Part key={source.key} title={source.name}>
          <SourceInputs source={source} />
        </Part>
      ))}
      {view.positions.length > 0 && (
        <Part title="Позиции в итоге среза">
          <Text size="sm">{view.positions.join(', ')}</Text>
          <Text size="xs" c="dimmed">
            Исходные данные каждой позиции — в её разборе на вкладке «Позиции».
          </Text>
        </Part>
      )}
      {positionId && params.get('position') !== positionId && (
        <Anchor component="button" size="sm" w="fit-content" onClick={() => setParams({ tab: 'positions', position: positionId })}>
          Открыть разбор позиции
        </Anchor>
      )}
    </Stack>
  );
}

/** A number that opens its origin in place. */
export function TracedNumber({ entry, children }: { entry: TraceNumber | undefined; children: ReactNode }) {
  if (!entry) return <>{children}</>;
  return (
    <Popover width={400} position="bottom-start" shadow="md" withArrow>
      <Popover.Target>
        <UnstyledButton component="span" className="ref-number" aria-label="Откуда это число">
          {children}
        </UnstyledButton>
      </Popover.Target>
      <Popover.Dropdown p={0}>
        <ScrollArea.Autosize mah={440} type="auto">
          <Stack gap="xs" p="md">
            <Text fw={600} size="sm">
              Откуда это число
            </Text>
            <OriginBody entry={entry} />
          </Stack>
        </ScrollArea.Autosize>
      </Popover.Dropdown>
    </Popover>
  );
}

export function OriginNote({ children }: { children: ReactNode }) {
  return (
    <Group gap={4} c="dimmed">
      <IconInfoCircle size={14} />
      <Text size="xs">{children}</Text>
    </Group>
  );
}
