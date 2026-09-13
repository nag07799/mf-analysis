import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Indian Equity Mutual Fund Overlap',
  description:
    'Compare the portfolios of any two Indian equity mutual funds using official monthly factsheet data.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
