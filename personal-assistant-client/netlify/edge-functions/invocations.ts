declare const Netlify: {
  env: {
    get(key: string): string | undefined;
  };
};

export default async (request: Request): Promise<Response> => {
  if (request.method !== "POST") {
    return new Response("Method Not Allowed", {
      status: 405,
      headers: { Allow: "POST" },
    });
  }

  const apiKey = Netlify.env.get("AGENTARTS_API_KEY");
  const targetUrl = Netlify.env.get("AGENTARTS_INVOCATIONS_URL");
  if (!apiKey || !targetUrl) {
    return new Response("AgentArts proxy is not configured", { status: 500 });
  }

  const headers = new Headers(request.headers);
  headers.delete("content-length");
  headers.delete("host");
  headers.set("Authorization", `Bearer ${apiKey}`);

  return fetch(targetUrl, {
    method: "POST",
    headers,
    body: request.body,
    signal: request.signal,
  });
};

export const config = {
  path: "/invocations",
};
