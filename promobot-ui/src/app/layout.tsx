import type { Metadata } from 'next';
import { Assistant } from 'next/font/google';
import './globals.css';
import { AuthProvider } from '../components/auth/AuthProvider';

const assistant = Assistant({ subsets: ['hebrew', 'latin'] });

export const metadata: Metadata = {
  title: 'Promobot - העוזר האישי של צוות הפרומו',
  description: 'ממשק צ\'אט פנימי לצוות הפרומו',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="he" dir="rtl">
      <body className={`${assistant.className} text-slate-900 bg-slate-50 antialiased`}>
        <AuthProvider>
          {children}
        </AuthProvider>
      </body>
    </html>
  );
}
