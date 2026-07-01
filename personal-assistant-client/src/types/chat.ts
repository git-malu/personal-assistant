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
  system_message?: string;
  auth_url?: string;
  auth_required?: boolean;
  auth_complete?: boolean;
  auth_failed?: boolean;
  provider?: string;
  oauth2_state?: string;
}
