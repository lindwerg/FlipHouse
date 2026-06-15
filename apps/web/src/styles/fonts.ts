import { Archivo, Archivo_Narrow, IBM_Plex_Mono } from 'next/font/google';

// Swiss Pop typography (docs/design-reference/swiss-pop.html):
//   Archivo        — variable grotesque display/body
//   Archivo Narrow — condensed nav / labels
//   IBM Plex Mono  — data labels, kickers, numerals
// Each exposes a CSS variable consumed by @theme inline in global.css.
export const fontGrotesk = Archivo({
  subsets: ['latin'],
  variable: '--font-grotesk',
  display: 'swap',
});

export const fontNarrow = Archivo_Narrow({
  subsets: ['latin'],
  weight: ['500', '600', '700'],
  variable: '--font-narrow',
  display: 'swap',
});

export const fontMono = IBM_Plex_Mono({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  variable: '--font-mono',
  display: 'swap',
});

export const fontVariables = `${fontGrotesk.variable} ${fontNarrow.variable} ${fontMono.variable}`;
