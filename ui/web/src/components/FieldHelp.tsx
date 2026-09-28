import type { ReactNode } from 'react';
import { Hint } from './Term';

/** A field's label; its short explanation shows on hover, the way a term's does. */
export function FieldHelp({ label, help }: { label: ReactNode; help?: string }) {
  return help ? <Hint text={help}>{label}</Hint> : <>{label}</>;
}
