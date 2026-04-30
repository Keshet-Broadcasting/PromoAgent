'use client';

import React from 'react';
import { MessageSquare, FileText, BarChart3 } from 'lucide-react';
import Image from 'next/image';

interface EmptyStateProps {
  onSuggestionClick: (text: string) => void;
}

export function EmptyState({ onSuggestionClick }: EmptyStateProps) {
  const suggestions = [
    {
      icon: <MessageSquare size={20} />,
      text: 'כתוב לי טקסט פרומו לקמפיין חדש',
    },
    {
      icon: <FileText size={20} />,
      text: 'סכם את ההנחיות האחרונות לצוות',
    },
    {
      icon: <BarChart3 size={20} />,
      text: 'מה היו הביצועים של הקמפיין הקודם?',
    },
  ];

  return (
    <div className="flex flex-col items-center justify-center h-full p-8 text-center space-y-7 animate-in fade-in duration-500">
      <div className="relative w-16 h-16 flex items-center justify-center mb-2">
        <Image src="/logo.svg" alt="Keshet Logo" fill className="object-contain drop-shadow-md" priority />
      </div>
      
      <div className="space-y-3 max-w-md">
        <h2 className="text-2xl font-semibold text-slate-800">איך אוכל לעזור לך היום?</h2>
        <p className="text-slate-500 leading-relaxed">
          אני כאן כדי לעזור לך לכתוב, לתכנן ולנתח קמפיינים של פרומו.
          אפשר לשאול אותי שאלות או לבקש ממני לכתוב טקסטים.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 w-full max-w-3xl mt-8">
        {suggestions.map((suggestion, index) => (
          <button
            key={index}
            onClick={() => onSuggestionClick(suggestion.text)}
            className="flex flex-col items-center gap-3 p-6 bg-white border border-slate-200 rounded-xl hover:border-blue-300 hover:bg-blue-50/50 hover:shadow-md transition-all text-slate-700 group text-center"
          >
            <div className="text-blue-500 group-hover:scale-110 transition-transform">
              {suggestion.icon}
            </div>
            <span className="text-sm font-medium">{suggestion.text}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
