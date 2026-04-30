'use client';

import { useAuth } from '../components/auth/AuthProvider';
import { LoginPlaceholder } from '../components/auth/LoginPlaceholder';
import { Header } from '../components/layout/Header';
import { ChatWindow } from '../components/chat/ChatWindow';

export default function Home() {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="w-8 h-8 border-4 border-blue-600 border-t-transparent rounded-full animate-spin"></div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <LoginPlaceholder />;
  }

  return (
    <div className="flex flex-col h-screen max-h-screen overflow-hidden bg-white">
      <Header />
      <main className="flex-1 overflow-hidden relative">
        <div className="absolute inset-0 max-w-5xl mx-auto w-full shadow-sm border-x border-slate-100 bg-white">
          <ChatWindow />
        </div>
      </main>
    </div>
  );
}
