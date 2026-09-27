import { Popover, Text } from '@mantine/core';
import { IconHelpCircle, IconInfoCircle } from '@tabler/icons-react';
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';

/** Help never changes a form row's height. Hover, keyboard focus and touch all work. */
export function FieldHelp({ label, help }: { label: ReactNode; help: string }) {
  const [opened, setOpened] = useState(false);
  const id = useId();
  const focused = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  const open = () => { clearTimeout(timer.current); setOpened(true); };
  const leave = () => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => { if (!focused.current) setOpened(false); }, 150);
  };
  return (
    <span className="field-label" onMouseEnter={open} onMouseLeave={leave}>
      <span>{label}</span>
      <Popover opened={opened} onChange={setOpened} position="top-start" withArrow withinPortal width={340} withRoles={false}>
        <Popover.Target>
          <button type="button" className="field-help-trigger" aria-label={`Пояснение: ${typeof label === 'string' ? label : 'поле'}`}
            aria-expanded={opened} aria-describedby={opened ? id : undefined}
            onFocus={() => { focused.current = true; open(); }} onBlur={() => { focused.current = false; leave(); }}
            onClick={(event) => { event.preventDefault(); open(); }}
            onKeyDown={(event) => { if (event.key === 'Escape') { event.stopPropagation(); clearTimeout(timer.current); focused.current = false; setOpened(false); } }}>
            <IconInfoCircle size={16} aria-hidden />
          </button>
        </Popover.Target>
        <Popover.Dropdown id={id} role="tooltip" onMouseEnter={open} onMouseLeave={leave}>
          <Text size="sm" lh={1.5}>{help}</Text>
        </Popover.Dropdown>
      </Popover>
    </span>
  );
}

export interface ExplainedProps {
  label: ReactNode;
  description?: ReactNode;
}

/**
 * A label whose short explanation opens in place, under the label, on «?». The editor's grid
 * aligns the inputs of a row by their bottom edge, so an open explanation moves no input.
 */
export function useExplanation(label: ReactNode, text: string | undefined): ExplainedProps {
  const [opened, setOpened] = useState(false);
  if (!text) return { label };
  return {
    label: (
      <span className="field-label">
        <span>{label}</span>
        <button
          type="button"
          className="field-help-trigger"
          aria-expanded={opened}
          aria-label={opened ? 'Скрыть пояснение' : `Что такое «${typeof label === 'string' ? label : 'это поле'}»`}
          onClick={(event) => {
            event.preventDefault();
            setOpened(!opened);
          }}
        >
          <IconHelpCircle size={16} aria-hidden />
        </button>
      </span>
    ),
    description: opened ? text : undefined,
  };
}

/** `useExplanation` for an input that is not a component of its own. */
export function Explained({
  label,
  text,
  children,
}: {
  label: ReactNode;
  text?: string;
  children: (props: ExplainedProps) => ReactNode;
}) {
  const props = useExplanation(label, text);
  return <>{children(props)}</>;
}
