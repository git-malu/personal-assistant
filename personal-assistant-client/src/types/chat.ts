export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  isStreaming?: boolean;
}

export type ReportProgressSource = "github" | "email" | "calendar";

export type ReportProgressStage =
  | "preparing"
  | "github_context"
  | "activity_search"
  | "activity_detail"
  | "email_collection"
  | "calendar_collection"
  | "rendering";

export type ReportProgressStatus =
  | "running"
  | "complete"
  | "failed"
  | "skipped";

export interface ReportProgressPayload {
  sequence: number;
  source?: ReportProgressSource;
  stage: ReportProgressStage;
  status: ReportProgressStatus;
  current?: number;
  total?: number;
  discovered?: number;
}

export interface SSEEvent {
  type?: string;
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
  report_progress?: boolean;
  sequence?: number;
  source?: ReportProgressSource;
  stage?: ReportProgressStage;
  status?: ReportProgressStatus;
  current?: number;
  total?: number;
  discovered?: number;
  report_ready?: boolean;
  report_format?: 'markdown';
  report_filename?: string;
  report_content?: string;
  report_type?: 'daily' | 'weekly' | 'monthly' | 'custom';
  report_window?: {
    start_at?: string;
    end_at?: string;
    timezone?: string;
  };
}
