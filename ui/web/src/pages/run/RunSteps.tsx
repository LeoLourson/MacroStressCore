import { Box, Group, Loader, Text, ThemeIcon, Tooltip } from '@mantine/core';
import { IconCheck, IconClock, IconExclamationMark, IconX } from '@tabler/icons-react';
import type { ReactNode } from 'react';
import { Elapsed } from '../../components/Elapsed';
import type { StepState, StepView } from '../../lib/stages';

function Mark({ state, index }: { state: StepState; index: number }) {
  switch (state) {
    case 'done':
      return (
        <ThemeIcon size={20} radius="xl" color="gray" variant="light">
          <IconCheck size={12} />
        </ThemeIcon>
      );
    case 'running':
      return (
        <ThemeIcon size={20} radius="xl" color="gray" variant="light">
          <Loader size={10} color="gray" />
        </ThemeIcon>
      );
    case 'yours':
      return (
        <ThemeIcon size={20} radius="xl" color="yellow" variant="filled" c="dark.8">
          <IconExclamationMark size={12} />
        </ThemeIcon>
      );
    case 'others':
      return (
        <ThemeIcon size={20} radius="xl" color="gray" variant="light">
          <IconClock size={12} />
        </ThemeIcon>
      );
    case 'failed':
    case 'rejected':
      return (
        <ThemeIcon size={20} radius="xl" color="dark" variant="light">
          <IconX size={12} />
        </ThemeIcon>
      );
    default:
      return (
        <ThemeIcon size={20} radius="xl" color="gray" variant="outline" c="gray.7">
          <Text size="xs" fw={600}>
            {index + 1}
          </Text>
        </ThemeIcon>
      );
  }
}

/**
 * The whole path of the stress test in one line: done steps are quiet, the current one carries
 * its note, the rest are dimmed. On a phone only the current step is shown, with its number.
 * This person's move forward closes the line.
 */
export function RunSteps({ steps, action }: { steps: StepView[]; action?: ReactNode }) {
  // Where the run stands: the first step not done, or the last one once all are.
  const open = steps.findIndex((step) => step.state !== 'done');
  const here = open < 0 ? steps.length - 1 : open;
  const current = steps[here] ?? steps[steps.length - 1];
  const note = (step: StepView) =>
    step.note && (
      <Text span size="sm" className="nowrap" c={step.state === 'yours' ? 'dark.8' : 'dimmed'} fw={step.state === 'yours' ? 600 : 400}>
        {step.note}
        {step.since && (
          <>
            {' · '}
            <Elapsed since={step.since} />
          </>
        )}
      </Text>
    );
  return (
    <Group justify="space-between" gap="sm" wrap="nowrap" mih={30}>
      <Group gap="sm" wrap="nowrap" hiddenFrom="md" style={{ minWidth: 0 }}>
        <Mark state={current.state} index={here} />
        <Text size="sm">
          <Text span size="sm" c="dimmed">
            Шаг {here + 1} из {steps.length}:{' '}
          </Text>
          <Text span size="sm" fw={600}>
            {current.title}
          </Text>
          {current.note && ' · '}
          {note(current)}
        </Text>
      </Group>
      <Group gap={0} wrap="nowrap" visibleFrom="md" component="ol" style={{ listStyle: 'none', padding: 0, margin: 0, minWidth: 0 }}>
        {steps.map((step, index) => {
          const now = index === here;
          // A step behind is only its mark: its name and result pop up. What is now and ahead is named.
          const behind = !now && step.state === 'done';
          const mark = <Mark state={step.state} index={index} />;
          return (
            // The steps ahead give way first when the line is short: their names are cut, not the current one.
            <Group key={step.title} component="li" gap={8} wrap="nowrap" aria-current={now ? 'step' : undefined} style={step.state === 'todo' ? { flexShrink: 1, minWidth: 0 } : { flexShrink: 0 }}>
              {index > 0 && <Box w={16} h={1} bg="gray.4" mx={6} style={{ flexShrink: 0 }} />}
              {behind ? (
                <Tooltip label={`${step.title}${step.note ? ` · ${step.note}` : ''}`}>
                  <span tabIndex={0} aria-label={step.title} style={{ display: 'inline-flex' }}>
                    {mark}
                  </span>
                </Tooltip>
              ) : (
                <>
                  {mark}
                  <Text size="sm" fw={now ? 600 : 400} c={step.state === 'todo' ? 'dimmed' : 'dark.8'} truncate title={step.title}>
                    {step.title}
                  </Text>
                  {now && note(step)}
                </>
              )}
            </Group>
          );
        })}
      </Group>
      {action && <Box style={{ flexShrink: 0 }}>{action}</Box>}
    </Group>
  );
}
