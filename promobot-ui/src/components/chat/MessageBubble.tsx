'use client';

import React, { useState } from 'react';
import { Message } from '../../types/chat';
import { User, Copy, Check } from 'lucide-react';
import Image from 'next/image';

interface MessageBubbleProps {
  message: Message;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user';
  const [copied, setCopied] = useState(false);

  // Format time (e.g., "14:30")
  const timeString = new Intl.DateTimeFormat('he-IL', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(message.timestamp);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard write failed (e.g. browser permission denied).
      // The button stays in its default state — no copy confirmation shown.
    }
  };

  return (
    <div
      className={`flex w-full gap-4 mb-6 animate-in slide-in-from-bottom-2 duration-300 ${
        isUser ? 'flex-row-reverse' : 'flex-row'
      }`}
    >
      {/* Avatar */}
      <div
        className={`relative flex-shrink-0 w-9 h-9 rounded-full flex items-center justify-center shadow-sm border overflow-hidden ${
          isUser
            ? 'bg-slate-100 text-slate-600 border-slate-200'
            : 'bg-white border-slate-100'
        }`}
      >
        {isUser ? <User size={18} /> : <Image src="/logo.svg" alt="Keshet Logo" fill className="object-contain p-[5px]" />}
      </div>

      {/* Message Content */}
      <div
        className={`flex flex-col max-w-[80%] md:max-w-[70%] ${
          isUser ? 'items-end' : 'items-start'
        }`}
      >
        <div className="flex items-center gap-2 mb-1 px-1">
          <span className="text-xs font-medium text-slate-500">
            {isUser ? 'את/ה' : 'Promobot'}
          </span>
          <span className="text-[10px] text-slate-400">{timeString}</span>
        </div>

        <div
          className={`px-5 py-3.5 rounded-2xl shadow-sm text-[15px] leading-relaxed whitespace-pre-wrap ${
            isUser
              ? 'bg-blue-600 text-white rounded-tl-sm'
              : 'bg-white text-slate-800 border border-slate-200 rounded-tr-sm'
          }`}
          dir="auto"
        >
          {message.content}
        </div>

        {/* Copy button — always visible below assistant messages */}
        {!isUser && (
          <button
            onClick={handleCopy}
            className="flex items-center gap-1.5 mt-1.5 px-2 py-1 text-[11px] text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-md transition-colors"
            title="העתק תשובה"
          >
            {copied
              ? <><Check size={12} className="text-green-500" /><span className="text-green-500">הועתק</span></>
              : <><Copy size={12} /><span>העתק</span></>
            }
          </button>
        )}
      </div>
    </div>
  );
}
