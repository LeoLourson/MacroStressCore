// Formulas everywhere in the app are LaTeX typeset by KaTeX with its own bundled fonts; their
// colour and size follow the text around them (styles.css, .katex). MathText sets one line of
// text in which $...$ is a formula: a plugin's convention, a metric's or a factor's
// description. Whole pages with block formulas go through Markdown.
import katex from 'katex';
import 'katex/dist/katex.min.css';
import { Fragment } from 'react';

export const KATEX_OPTIONS = { throwOnError: false, strict: 'ignore' as const };

export function MathText({ children }: { children: string }) {
  return (
    <>
      {children.split(/(\$[^$]+\$)/g).map((part, index) =>
        part.length > 2 && part.startsWith('$') && part.endsWith('$') ? (
          <span key={index} dangerouslySetInnerHTML={{ __html: katex.renderToString(part.slice(1, -1), KATEX_OPTIONS) }} />
        ) : (
          <Fragment key={index}>{part}</Fragment>
        ),
      )}
    </>
  );
}
