'use client';

import React, { useEffect, useRef } from 'react';
import { Message } from '../../types/chat';
import { MessageBubble } from './MessageBubble';
import { LoadingState } from './LoadingState';
import { ErrorState } from './ErrorState';

interface MessageListProps {
  messages: Message[];
  isLoading: boolean;
  error: string | null;
  onRetry: () => void;
}

export function MessageList({ messages, isLoading, error, onRetry }: MessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (el) {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    }
  }, [messages, isLoading]);

  return (
    <div ref={containerRef} className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-6 bg-slate-50/50 scroll-smooth">
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}
      
      {isLoading && (
        <div className="flex w-full gap-4 mb-6 animate-in fade-in duration-300">
          <LoadingState />
        </div>
      )}

      {error && (
        <div className="flex justify-center w-full mt-4">
          <ErrorState message={error} onRetry={onRetry} />
        </div>
      )}

      <div className="h-4" />
    </div>
  );
}
