'use client';

import React from 'react';
import { useAuth } from '../auth/AuthProvider';
import { LogOut } from 'lucide-react';
import Image from 'next/image';

export function Header() {
  const { user, logout } = useAuth();

  return (
    <header className="bg-white border-b border-slate-200 px-6 py-4 flex items-center justify-between sticky top-0 z-10 shadow-sm">
      <div className="flex items-center gap-3.5">
        <div className="relative w-9 h-9 flex items-center justify-center flex-shrink-0">
          <Image src="/logo.svg" alt="Keshet Logo" fill className="object-contain drop-shadow-sm" priority />
        </div>
        <div className="flex flex-col justify-center">
          <h1 className="text-[17px] font-bold text-slate-900 leading-tight tracking-tight">Promobot</h1>
          <p className="text-[13px] text-slate-500 leading-tight mt-0.5">העוזר האישי של צוות הפרומו</p>
        </div>
      </div>
      
      {user && (
        <div className="flex items-center gap-4">
          <div className="hidden sm:block text-left">
            <p className="text-sm font-medium text-slate-700" dir="auto">{user.name}</p>
            <p className="text-xs text-slate-500" dir="ltr">{user.email}</p>
          </div>
          <button
            onClick={logout}
            className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-full transition-colors"
            title="התנתק"
            aria-label="התנתק"
          >
            <LogOut size={20} />
          </button>
        </div>
      )}
    </header>
  );
}
