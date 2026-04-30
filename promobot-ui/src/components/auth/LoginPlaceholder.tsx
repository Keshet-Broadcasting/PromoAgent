'use client';

import React from 'react';
import { useAuth } from './AuthProvider';
import Image from 'next/image';

export function LoginPlaceholder() {
  const { login, isLoading } = useAuth();

  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-slate-50 text-slate-900">
      <div className="max-w-md w-full p-8 bg-white rounded-xl shadow-sm border border-slate-200 text-center space-y-6">
        <div className="relative w-16 h-16 mx-auto mb-2 flex items-center justify-center">
          <Image src="/logo.svg" alt="Keshet Logo" fill className="object-contain drop-shadow-md" priority />
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">ברוכים הבאים ל-Promobot</h1>
        <p className="text-slate-500">
          העוזר האישי של צוות הפרומו. אנא התחברו כדי להמשיך.
        </p>
        <button
          onClick={login}
          disabled={isLoading}
          className="w-full py-3 px-4 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
        >
          {isLoading ? (
            <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
          ) : (
            'התחברות (Microsoft Entra)'
          )}
        </button>
      </div>
    </div>
  );
}
