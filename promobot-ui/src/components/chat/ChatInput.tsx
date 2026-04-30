'use client';

import React, { useState, useRef, useEffect } from 'react';
import { Send, Paperclip, Loader2 } from 'lucide-react';

interface ChatInputProps {
  onSend: (message: string) => void;
  isLoading: boolean;
}

export function ChatInput({ onSend, isLoading }: ChatInputProps) {
  const [input, setInput] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(
        textareaRef.current.scrollHeight,
        200
      )}px`;
    }
  }, [input]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (input.trim() && !isLoading) {
      onSend(input.trim());
      setInput('');
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto';
      }
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <div className="p-4 bg-white border-t border-slate-200">
      <form
        onSubmit={handleSubmit}
        className="max-w-4xl mx-auto flex items-end gap-3 relative"
      >
        <button
          type="button"
          className="p-3 text-slate-400 hover:text-blue-600 hover:bg-blue-50 rounded-xl transition-colors mb-1 shadow-sm border border-transparent hover:border-blue-100"
          title="הוסף קובץ (בקרוב)"
          aria-label="הוסף קובץ"
        >
          <Paperclip size={20} />
        </button>

        <div className="relative flex-1 bg-slate-50 border border-slate-200 rounded-2xl shadow-sm focus-within:border-blue-500 focus-within:ring-1 focus-within:ring-blue-500/20 transition-all">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="הקלד/י הודעה ל-Promobot..."
            disabled={isLoading}
            className="w-full max-h-[200px] min-h-[56px] py-4 px-5 bg-transparent border-none resize-none focus:outline-none text-slate-800 placeholder:text-slate-400 text-base leading-relaxed"
            dir="auto"
            rows={1}
          />
        </div>

        <button
          type="submit"
          disabled={!input.trim() || isLoading}
          className="p-3.5 bg-blue-600 text-white rounded-xl hover:bg-blue-700 transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-sm mb-1 group"
          title="שלח הודעה"
          aria-label="שלח הודעה"
        >
          {isLoading ? (
            <Loader2 size={20} className="animate-spin" />
          ) : (
            <Send size={20} className="rtl:-scale-x-100 group-hover:translate-x-[-2px] transition-transform" />
          )}
        </button>
      </form>
      <div className="text-center mt-3">
        <p className="text-xs text-slate-400">
          Promobot יכול לטעות. אנא בדקו עובדות חשובות.
        </p>
      </div>
    </div>
  );
}
