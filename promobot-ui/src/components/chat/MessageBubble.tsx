'use client';

import React, { useState } from 'react';
import { Message } from '../../types/chat';
import { User, Copy, Check } from 'lucide-react';
import Image from 'next/image';

interface MessageBubbleProps {
  message: Message;
}

type InlinePart = {
  text: string;
  strong: boolean;
};

type RenderBlock =
  | { type: 'heading'; level: number; content: string }
  | { type: 'paragraph'; content: string; detail?: boolean }
  | { type: 'list'; ordered: boolean; items: { marker: string; content: string }[] };

function parseInline(text: string): InlinePart[] {
  return text
    .split(/(\*\*[^*]+\*\*)/g)
    .filter(Boolean)
    .map((part) => {
      const strong = part.startsWith('**') && part.endsWith('**');
      return {
        strong,
        text: strong ? part.slice(2, -2) : part,
      };
    });
}

function renderInline(text: string) {
  return parseInline(text).map((part, index) =>
    part.strong ? (
      <strong key={index} className="font-semibold text-slate-900">
        {part.text}
      </strong>
    ) : (
      <React.Fragment key={index}>{part.text}</React.Fragment>
    )
  );
}

function parseAssistantMessage(content: string): RenderBlock[] {
  const blocks: RenderBlock[] = [];

  for (const rawLine of content.split('\n')) {
    const line = rawLine.trimEnd();
    const trimmed = line.trim();
    if (!trimmed) continue;

    const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      blocks.push({
        type: 'heading',
        level: headingMatch[1].length,
        content: headingMatch[2],
      });
      continue;
    }

    const orderedMatch = trimmed.match(/^(\d+)\.\s+(.+)$/);
    if (orderedMatch) {
      const previous = blocks[blocks.length - 1];
      const item = { marker: orderedMatch[1], content: orderedMatch[2] };
      if (previous?.type === 'list' && previous.ordered) {
        previous.items.push(item);
      } else {
        blocks.push({ type: 'list', ordered: true, items: [item] });
      }
      continue;
    }

    const bulletMatch = trimmed.match(/^[-*•]\s+(.+)$/);
    if (bulletMatch) {
      const previous = blocks[blocks.length - 1];
      const item = { marker: '•', content: bulletMatch[1] };
      if (previous?.type === 'list' && !previous.ordered) {
        previous.items.push(item);
      } else {
        blocks.push({ type: 'list', ordered: false, items: [item] });
      }
      continue;
    }

    blocks.push({
      type: 'paragraph',
      content: trimmed,
      detail: /^\s{2,}/.test(rawLine) || trimmed.startsWith('מקור:'),
    });
  }

  return blocks;
}

function AssistantContent({ content }: { content: string }) {
  return (
    <div className="space-y-3" dir="auto">
      {parseAssistantMessage(content).map((block, blockIndex) => {
        if (block.type === 'heading') {
          const className = block.level <= 2
            ? 'text-base font-semibold text-slate-900 mt-1'
            : 'text-[15px] font-semibold text-slate-900 mt-1';

          return (
            <h3 key={blockIndex} className={className}>
              {renderInline(block.content)}
            </h3>
          );
        }

        if (block.type === 'list') {
          return (
            <div key={blockIndex} className="space-y-2">
              {block.items.map((item, itemIndex) => (
                <div key={itemIndex} className="flex gap-2 text-[15px] leading-relaxed">
                  <span className="min-w-5 text-slate-500 font-medium">
                    {block.ordered ? `${item.marker}.` : item.marker}
                  </span>
                  <span className="flex-1">{renderInline(item.content)}</span>
                </div>
              ))}
            </div>
          );
        }

        return (
          <p
            key={blockIndex}
            className={block.detail ? 'text-sm text-slate-600 leading-relaxed' : 'text-[15px] leading-relaxed'}
          >
            {renderInline(block.content)}
          </p>
        );
      })}
    </div>
  );
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
    const text = message.content;

    // Modern Clipboard API (requires clipboard-write permission — may be blocked in iframes)
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
        return;
      } catch {
        // Fall through to legacy execCommand fallback
      }
    }

    // Legacy fallback: works inside iframes without any special permission
    try {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.cssText = 'position:fixed;top:0;left:0;opacity:0;pointer-events:none';
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(textarea);
      if (ok) {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }
    } catch {
      // Both methods failed — button stays in default state
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
          className={`px-5 py-3.5 rounded-2xl shadow-sm text-[15px] leading-relaxed ${
            isUser
              ? 'bg-blue-600 text-white rounded-tl-sm whitespace-pre-wrap'
              : 'bg-white text-slate-800 border border-slate-200 rounded-tr-sm'
          }`}
          dir="auto"
        >
          {isUser ? message.content : <AssistantContent content={message.content} />}
        </div>

        {/* Copy button — always visible below assistant messages */}
        {!isUser && (
          <button
            type="button"
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
