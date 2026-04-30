'use client';

import React, { useState } from 'react';
import { Message, ChatState } from '../../types/chat';
import { chatService, ApiError } from '../../services/api';
import { useAuth } from '../auth/AuthProvider';
import { MessageList } from './MessageList';
import { ChatInput } from './ChatInput';
import { EmptyState } from './EmptyState';

export function ChatWindow() {
  const { getToken } = useAuth();
  const [state, setState] = useState<ChatState>({
    messages: [],
    isLoading: false,
    error: null,
  });

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

      setState((prev) => ({
        ...prev,
        messages: [...prev.messages, responseMessage],
        isLoading: false,
      }));
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

  return (
    <div className="flex flex-col h-full bg-slate-50/50">
      {state.messages.length === 0 ? (
        <EmptyState onSuggestionClick={handleSendMessage} />
      ) : (
        <MessageList
          messages={state.messages}
          isLoading={state.isLoading}
          error={state.error}
          onRetry={handleRetry}
        />
      )}
      <ChatInput onSend={handleSendMessage} isLoading={state.isLoading} />
    </div>
  );
}
