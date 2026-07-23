import {
  applyExpiredCallbackContextCookies,
} from "../_shared/callback-context.js";
import {
  buildExpiredRuntimeSessionCookie,
} from "../_shared/runtime-session.js";

export async function onRequestPost({ env }) {
  const headers = new Headers({ "Cache-Control": "no-store" });
  headers.append("Set-Cookie", buildExpiredRuntimeSessionCookie(env));
  applyExpiredCallbackContextCookies(headers);
  return new Response(null, { status: 204, headers });
}
