'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { Message, ChatState } from '../../types/chat';
import { chatService, ApiError } from '../../services/api';
import { useAuth } from '../auth/AuthProvider';
import { MessageList } from './MessageList';
import { ChatInput } from './ChatInput';
import { EmptyState } from './EmptyState';

const STORAGE_KEY = 'promobot-chat-history';

function loadHistory(): Message[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as Message[];
    return parsed.map(m => ({ ...m, timestamp: new Date(m.timestamp) }));
  } catch {
    return [];
  }
}

function saveHistory(messages: Message[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
  } catch { /* quota exceeded — silently drop */ }
}

export function ChatWindow() {
  const { getToken } = useAuth();
  const [state, setState] = useState<ChatState>({
    messages: [],
    isLoading: false,
    error: null,
  });

  useEffect(() => {
    const saved = loadHistory();
    if (saved.length > 0) {
      setState(prev => ({ ...prev, messages: saved }));
    }
  }, []);

  const sendToBackend = async (messagesToSend: Message[]) => {
    setState((prev) => ({
      ...prev,
      isLoading: true,
      error: null,
    }));

    try {
      const token = await getToken();
      const responseMessage = await chatService.sendMessage(
        messagesToSend,
        token || undefined
      );

      setState((prev) => {
        const updated = [...prev.messages, responseMessage];
        saveHistory(updated);
        return { ...prev, messages: updated, isLoading: false };
      });
    } catch (error) {
      console.error('Failed to send message:', error);
      let errorMessage = 'אירעה שגיאה לא צפויה. אנא נסו שוב.';
      
      if (error instanceof ApiError) {
        errorMessage = error.message;
      }

      setState((prev) => ({
        ...prev,
        isLoading: false,
        error: errorMessage,
      }));
    }
  };

  const handleSendMessage = async (content: string) => {
    if (!content.trim()) return;

    const newUserMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: content.trim(),
      timestamp: new Date(),
    };

    const updatedMessages = [...state.messages, newUserMessage];
    saveHistory(updatedMessages);

    setState((prev) => ({
      ...prev,
      messages: updatedMessages,
    }));

    await sendToBackend(updatedMessages);
  };

  const handleRetry = async () => {
    if (state.messages.length > 0) {
      await sendToBackend(state.messages);
    }
  };

  const handleNewChat = useCallback(() => {
    setState({ messages: [], isLoading: false, error: null });
    localStorage.removeItem(STORAGE_KEY);
  }, []);

  return (
    <div className="flex flex-col h-full bg-slate-50/50">
      {state.messages.length === 0 ? (
        <EmptyState />
      ) : (
        <>
          <div className="flex justify-end p-2">
            <button
              onClick={handleNewChat}
              className="text-xs text-slate-500 hover:text-slate-700 px-3 py-1.5 rounded-md hover:bg-slate-100 transition-colors"
            >
              שיחה חדשה
            </button>
          </div>
          <MessageList
            messages={state.messages}
            isLoading={state.isLoading}
            error={state.error}
            onRetry={handleRetry}
          />
        </>
      )}
      <ChatInput onSend={handleSendMessage} isLoading={state.isLoading} />
    </div>
  );
}
