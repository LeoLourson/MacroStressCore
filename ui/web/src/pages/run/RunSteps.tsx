import { Box, Group, Loader, SimpleGrid, Stack, Text, ThemeIcon } from '@mantine/core';
import { IconCheck, IconClock, IconExclamationMark, IconX } from '@tabler/icons-react';
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
        <ThemeIcon size={20} radius="xl" color="gray" variant="outline" c="gray.6">
          <Text size="xs" fw={600}>
            {index + 1}
          </Text>
        </ThemeIcon>
      );
  }
}

/** The whole path of the stress test: what is done, where it is now, what is still ahead. */
export function RunSteps({ steps }: { steps: StepView[] }) {
  return (
    <SimpleGrid cols={{ base: 1, sm: 3, lg: steps.length }} spacing="xs" component="ol" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
      {steps.map((step, index) => {
        const current = step.state !== 'done' && step.state !== 'todo';
        return (
          <Box
            component="li"
            key={step.title}
            py={4}
            aria-current={current ? 'step' : undefined}
          >
            <Group gap="sm" wrap="nowrap" align="flex-start">
              <Mark state={step.state} index={index} />
              <Stack gap={4} miw={0}>
                <Text size="sm" fw={current ? 600 : 400} c={step.state === 'todo' ? 'dimmed' : undefined}>
                  {step.title}
                </Text>
                {step.note && (
                  <Text size="xs" c={step.state === 'yours' ? 'dark.8' : 'dimmed'} fw={step.state === 'yours' ? 600 : 400}>
                    {step.note}
                    {step.since && (
                      <>
                        {' · '}
                        <Elapsed since={step.since} />
                      </>
                    )}
                  </Text>
                )}
              </Stack>
            </Group>
          </Box>
        );
      })}
    </SimpleGrid>
  );
}
