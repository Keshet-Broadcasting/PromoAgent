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
    // The backend currently expects a single question, not full chat history
    const lastMessage = messages[messages.length - 1];
    
    try {
      const response = await fetch(API_ENDPOINT, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ 
          question: lastMessage.content,
          debug: false 
        }),
      });

      if (!response.ok) {
        let errorBody = '';
        try {
          const errData = await response.json();
          errorBody = errData.detail || errData.message || JSON.stringify(errData);
        } catch (e) {
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
