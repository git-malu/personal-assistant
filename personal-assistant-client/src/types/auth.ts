/** GET /api/auth/me response. */
export interface UserInfo {
  user_id: string;
  display_name: string;
  email: string;
  channel: 'entra_id';
  is_authenticated: boolean;
}

/** OAuth error response. */
export interface AuthErrorResponse {
  error: string;
  error_description?: string | null;
}
