import { Alert, Anchor, Collapse, Stack, Text } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { IconAlertCircle } from '@tabler/icons-react';
import { ApiError } from '../api/client';

/** A human message first; the technical detail stays folded for whoever needs it. */
export function ErrorAlert({ error, title }: { error: unknown; title?: string }) {
  const [open, { toggle }] = useDisclosure(false);
  if (!error) return null;
  const api = error instanceof ApiError ? error : null;
  const message = api ? api.userMessage : 'Что-то пошло не так. Обновите страницу.';
  const details = api
    ? [api.detail, ...api.violations.map((v) => [v.rule_id, v.path, v.message].filter(Boolean).join(' '))]
    : [String(error)];
  const shown = details.filter(Boolean);
  return (
    <Alert color="orange" icon={<IconAlertCircle />} title={title ?? message} variant="light">
      <Stack gap={4}>
        {title && <Text size="sm">{message}</Text>}
        {shown.length > 0 && (
          <>
            <Anchor component="button" type="button" size="xs" onClick={toggle} c="dimmed">
              {open ? 'Скрыть подробности' : 'Подробнее'}
            </Anchor>
            <Collapse in={open}>
              <Text size="xs" c="dimmed" ff="monospace" style={{ whiteSpace: 'pre-wrap' }}>
                {shown.join('\n')}
              </Text>
            </Collapse>
          </>
        )}
      </Stack>
    </Alert>
  );
}
