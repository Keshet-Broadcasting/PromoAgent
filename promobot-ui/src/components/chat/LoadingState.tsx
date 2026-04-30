'use client';

import React from 'react';

export function LoadingState() {
  return (
    <div className="flex items-center gap-2 p-4 bg-slate-100/50 rounded-2xl rounded-tr-sm self-start max-w-[85%] text-slate-500 animate-pulse border border-slate-200 shadow-sm">
      <div className="w-2 h-2 bg-blue-400 rounded-full animate-bounce [animation-delay:-0.3s]"></div>
      <div className="w-2 h-2 bg-blue-400 rounded-full animate-bounce [animation-delay:-0.15s]"></div>
      <div className="w-2 h-2 bg-blue-400 rounded-full animate-bounce"></div>
      <span className="mr-2 text-sm font-medium">Promobot חושב...</span>
    </div>
  );
}
