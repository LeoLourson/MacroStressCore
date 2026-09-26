import { createTheme, type CSSVariablesResolver, type MantineColorsTuple } from '@mantine/core';

// The one cold accent: everything that can be pressed or followed.
const steel: MantineColorsTuple = [
  '#edf3f8',
  '#dbe5ee',
  '#b3c8da',
  '#88a9c5',
  '#648fb3',
  '#4d7ea8',
  '#3c6d97',
  '#2d5f87',
  '#244f72',
  '#1a3d59',
];

// MTS red belongs to identity and to the approval only: the logo, the approve button, the stamp.
const mts: MantineColorsTuple = [
  '#ffe9ea',
  '#ffd1d3',
  '#fca2a6',
  '#f86f75',
  '#f3434b',
  '#ef2630',
  '#e30611',
  '#c9000c',
  '#b30009',
  '#9c0006',
];

const sans = '"Golos Text", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

export const theme = createTheme({
  primaryColor: 'steel',
  primaryShade: 7,
  colors: { steel, mts },
  fontFamily: sans,
  fontFamilyMonospace: 'ui-monospace, "Cascadia Mono", Consolas, monospace',
  headings: { fontFamily: sans, fontWeight: '600' },
  defaultRadius: 'md',
  cursorType: 'pointer',
  components: {
    Tooltip: { defaultProps: { multiline: true, maw: 320, withArrow: true, openDelay: 150 } },
    Paper: { defaultProps: { withBorder: true, radius: 'md' } },
    // Tinted alerts keep their colour in the icon and background; the title stays ink for contrast.
    Alert: { styles: { title: { color: 'var(--mantine-color-dark-8)' } } },
  },
});

// Secondary text at 5.9:1 on white and 5.5:1 on the page grey: the default dimmed is 3.3:1.
export const resolveVariables: CSSVariablesResolver = () => ({
  variables: {},
  light: { '--mantine-color-dimmed': '#5b6570' },
  dark: {},
});
