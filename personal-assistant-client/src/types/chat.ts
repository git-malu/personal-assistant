export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  isStreaming?: boolean;
}

export interface SSEEvent {
  token?: string;
  done?: boolean;
  error?: string;
}
