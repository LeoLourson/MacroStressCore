import { Tooltip } from '@mantine/core';
import { IconInfoCircle } from '@tabler/icons-react';
import type { ReactNode } from 'react';
import { GLOSSARY } from '../lib/labels';
import { pluginGlossary } from '../plugins';

/**
 * The one way a hint is shown: words with a small info mark, the explanation pops up on hover,
 * keyboard focus or touch. Headings, field labels and terms in text all use it.
 */
export function Hint({ text, children }: { text: ReactNode; children: ReactNode }) {
  return (
    <Tooltip label={text} multiline maw={360} events={{ hover: true, focus: true, touch: true }}>
      <span className="hint" tabIndex={0}>
        {children}
        <IconInfoCircle className="hint-mark" aria-hidden />
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
