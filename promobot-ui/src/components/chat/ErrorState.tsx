'use client';

import React from 'react';
import { AlertCircle, RefreshCw } from 'lucide-react';

interface ErrorStateProps {
  message: string;
  onRetry: () => void;
}

export function ErrorState({ message, onRetry }: ErrorStateProps) {
  return (
    <div className="flex flex-col items-center justify-center p-6 bg-red-50 border border-red-200 rounded-xl text-red-800 max-w-md mx-auto my-4 shadow-sm">
      <AlertCircle size={32} className="text-red-500 mb-3" />
      <h3 className="font-semibold text-lg mb-1">אופס! משהו השתבש</h3>
      <p className="text-sm text-red-600 text-center mb-4">{message}</p>
      <button
        onClick={onRetry}
        className="flex items-center gap-2 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors shadow-sm font-medium"
      >
        <RefreshCw size={16} />
        <span>נסה שוב</span>
      </button>
    </div>
  );
}
