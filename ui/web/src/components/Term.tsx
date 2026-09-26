import { Tooltip } from '@mantine/core';
import type { ReactNode } from 'react';
import { GLOSSARY } from '../lib/labels';
import { pluginGlossary } from '../plugins';

/** A domain term with its one-sentence explanation on hover: the platform's or a plugin's. */
export function Term({ name, children }: { name: string; children?: ReactNode }) {
  const hint = GLOSSARY[name] ?? pluginGlossary()[name];
  if (!hint) return <>{children ?? name}</>;
  return (
    <Tooltip label={hint}>
      <span className="term" tabIndex={0}>
        {children ?? name}
      </span>
    </Tooltip>
  );
}
