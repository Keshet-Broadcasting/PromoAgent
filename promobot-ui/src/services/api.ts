import { Message } from '../types/chat';

// Default to localhost:8000 for local FastAPI development
const API_ENDPOINT = process.env.NEXT_PUBLIC_API_ENDPOINT || 'http://localhost:8000/query';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

export const chatService = {
  /**
   * Sends a message to the backend agent and returns the response.
   * Prepared for Entra ID token injection.
   */
  async sendMessage(messages: Message[], token?: string): Promise<Message> {
    const lastMessage = messages[messages.length - 1];

    const MAX_HISTORY = 10;
    const priorMessages = messages.slice(0, -1).slice(-MAX_HISTORY);
    // Filter to only roles accepted by the backend (Literal["user", "assistant"]).
    // The UI's Role type also includes 'system'; sending that causes a 422.
    const history = priorMessages
      .filter((m): m is typeof m & { role: 'user' | 'assistant' } =>
        m.role === 'user' || m.role === 'assistant'
      )
      .map(m => ({ role: m.role, content: m.content }));
    
    try {
      const response = await fetch(API_ENDPOINT, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ 
          question: lastMessage.content,
          history: history.length > 0 ? history : undefined,
          debug: false,
        }),
      });

      if (!response.ok) {
        let errorBody = '';
        try {
          const errData = await response.json();
          const detail = errData.detail;
          if (typeof detail === 'string') {
            errorBody = detail;
          } else if (Array.isArray(detail)) {
            // FastAPI validation errors: [{loc, msg, type}, ...]
            errorBody = detail
              .map((e: { msg?: string }) => e.msg ?? JSON.stringify(e))
              .join('; ');
          } else {
            errorBody = (typeof errData.error === 'string' ? errData.error : null)
              ?? (typeof errData.message === 'string' ? errData.message : null)
              ?? JSON.stringify(errData);
          }
        } catch {
          errorBody = await response.text().catch(() => '');
        }
        console.error('Backend error response:', response.status, errorBody);
        throw new ApiError(response.status, `שגיאת שרת (${response.status}): ${errorBody || response.statusText}`);
      }

      const data = await response.json();
      
      // The backend returns: { answer: string, route: string, confidence: string, sources: [], trace_id: string }
      return {
        id: data.trace_id || Date.now().toString(),
        role: 'assistant',
        content: data.answer,
        timestamp: new Date(),
      };
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(500, 'אירעה שגיאה בתקשורת עם השרת. ודא שהשרת (FastAPI) רץ ברקע.');
    }
  },
};
