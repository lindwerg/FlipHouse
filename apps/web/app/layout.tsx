import type { ReactNode } from 'react';

export const metadata = {
  title: 'FlipHouse',
  description: 'FlipHouse — viral clips with native offers.',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
