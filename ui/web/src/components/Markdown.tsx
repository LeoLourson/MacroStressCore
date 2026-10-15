// Markdown with formulas: $...$ in a line, $$...$$ as a block, typeset by KaTeX with the same
// options and styles as MathText, so a formula looks the same on every screen. Paragraphs,
// lists, tables and headings take the app's type scale.
import { Anchor, Code, List, Table, Text, Title } from '@mantine/core';
import type { Element, ElementContent, Root } from 'hast';
import ReactMarkdown, { type Components } from 'react-markdown';
import rehypeKatex from 'rehype-katex';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import { KATEX_OPTIONS } from './MathText';

/** A formula keeps the punctuation after it on its line: «$x$,» never breaks before the comma. */
function keepPunctuation() {
  const PUNCTUATION = /^[.,;:!?)»]+/;
  const isFormula = (node: ElementContent): node is Element =>
    node.type === 'element' && String(node.properties?.className ?? '').includes('katex');
  function walk(node: Root | Element) {
    const children = node.children as ElementContent[];
    for (let i = 0; i < children.length; i += 1) {
      const child = children[i];
      const next = children[i + 1];
      if (isFormula(child) && next?.type === 'text') {
        const mark = PUNCTUATION.exec(next.value)?.[0];
        if (mark) {
          next.value = next.value.slice(mark.length);
          children[i] = {
            type: 'element',
            tagName: 'span',
            properties: { className: ['math-nowrap'] },
            children: [child, { type: 'text', value: mark }],
          };
        }
      } else if (child.type === 'element') walk(child);
    }
  }
  return (tree: Root) => walk(tree);
}

const COMPONENTS: Components = {
  h2: ({ children }) => <Title order={3}>{children}</Title>,
  h3: ({ children }) => <Title order={4}>{children}</Title>,
  p: ({ children }) => (
    <Text size="sm" lh={1.6}>
      {children}
    </Text>
  ),
  ul: ({ children }) => (
    <List size="sm" spacing={4} lh={1.6}>
      {children}
    </List>
  ),
  ol: ({ children }) => (
    <List type="ordered" size="sm" spacing={4} lh={1.6}>
      {children}
    </List>
  ),
  li: ({ children }) => <List.Item>{children}</List.Item>,
  a: ({ href, children }) => (
    <Anchor href={href} size="sm">
      {children}
    </Anchor>
  ),
  code: ({ children }) => <Code>{children}</Code>,
  // A table wider than the column scrolls inside it and never widens the page.
  table: ({ children }) => (
    <div className="doc-table-wrap">
      <Table className="doc-table" verticalSpacing={6} fz="sm">
        {children}
      </Table>
    </div>
  ),
  thead: ({ children }) => <Table.Thead>{children}</Table.Thead>,
  tbody: ({ children }) => <Table.Tbody>{children}</Table.Tbody>,
  tr: ({ children }) => <Table.Tr>{children}</Table.Tr>,
  th: ({ children }) => <Table.Th>{children}</Table.Th>,
  td: ({ children }) => <Table.Td>{children}</Table.Td>,
};

export function Markdown({ children }: { children: string }) {
  return (
    <div className="doc-prose">
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[[rehypeKatex, KATEX_OPTIONS], keepPunctuation]} components={COMPONENTS}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
