// Netlify Edge Function: invocations.ts
//
// 拦截浏览器对 /invocations 的 POST 请求，
// 加上 Bearer token 认证头和 Session ID 后转发到 AgentArts Gateway，
// 并流式返回后端 SSE 响应。由于运行在 Edge 端，原生支持 streaming 响应。
//
// AgentArts Gateway 路由路径为 /runtimes/{agent_name}/invocations，
// 需要 Authorization: Bearer token 和 x-hw-agentarts-session-id 头。

export default async (request: Request) => {
  // 仅允许 POST 请求
  if (request.method !== "POST") {
    return new Response("Method Not Allowed", { status: 405 });
  }

  const gatewayUrl = "https://defaultgw-ha3wenzqga.cn-southwest-2.huaweicloud-agentarts.com/runtimes/personal-assistant/invocations";

  // 优先从环境变量获取 API Key，如果没有则回退到本地 dev key
  // 注意：在 Deno 环境（Netlify Edge Functions）中，使用 Netlify.env.get() 获取环境变量
  const apiKey = Netlify.env.get("AGENTARTS_API_KEY") || "pa-dev-api-key-2026";

  // 为每个请求生成唯一的 Session ID（AgentArts Gateway 要求）
  const sessionId = crypto.randomUUID();

  try {
    // 先读取完整的请求体（对于聊天消息，body 很小，不会有内存问题）
    const bodyText = await request.text();
    const bodyBytes = new TextEncoder().encode(bodyText);

    // 转发请求到 AgentArts Gateway
    const response = await fetch(gatewayUrl, {
      method: "POST",
      headers: {
        "Content-Type": request.headers.get("content-type") || "application/json",
        "Accept": request.headers.get("accept") || "text/event-stream",
        "Authorization": `Bearer ${apiKey}`,
        "x-hw-agentarts-session-id": sessionId,
        "Content-Length": String(bodyBytes.length),
      },
      body: bodyText,
      signal: request.signal,
    });

    // 将后端的响应（包括 status、headers、stream body）原样返回给浏览器
    return response;
  } catch (error) {
    return new Response(
      JSON.stringify({ error: "Gateway unreachable", details: String(error) }),
      {
        status: 502,
        headers: { "Content-Type": "application/json" },
      }
    );
  }
};

// Edge Function 配置路由
export const config = {
  path: "/invocations",
};
