import { Tooltip } from '@mantine/core';
import type { ReactNode } from 'react';
import { GLOSSARY } from '../lib/labels';
import { pluginGlossary } from '../plugins';

/** Words with a short explanation on hover, keyboard focus or touch; a dotted underline marks them. */
export function Hint({ text, children }: { text: ReactNode; children: ReactNode }) {
  return (
    <Tooltip label={text} multiline maw={360} events={{ hover: true, focus: true, touch: true }}>
      <span className="term" tabIndex={0}>
        {children}
      </span>
    </Tooltip>
  );
}

/** A domain term with its one-sentence explanation on hover: the platform's or a plugin's. */
export function Term({ name, children }: { name: string; children?: ReactNode }) {
  const hint = GLOSSARY[name] ?? pluginGlossary()[name];
  if (!hint) return <>{children ?? name}</>;
  return <Hint text={hint}>{children ?? name}</Hint>;
}
