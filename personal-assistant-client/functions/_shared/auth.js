let jwks;

function bearerToken(request) {
  const authorization = request.headers.get("authorization")?.trim() ?? "";
  return authorization.toLowerCase().startsWith("bearer ")
    ? authorization.slice(7).trim()
    : "";
}

export async function authenticateRequest(request, env) {
  const token = bearerToken(request);
  if (!token && env?.ALLOW_DEV_AUTH === "true") {
    return request.headers.get("x-hw-agentgateway-user-id") || "dev-user";
  }
  if (!token) {
    throw new Response(JSON.stringify({ message: "Authentication required" }), {
      status: 401,
      headers: { "content-type": "application/json" },
    });
  }

  if (!env?.OIDC_JWKS_URL || !env?.OIDC_ISSUER || !env?.OIDC_AUDIENCE) {
    if (env?.ALLOW_DEV_AUTH === "true") {
      const payload = JSON.parse(
        atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")),
      );
      return payload.oid || payload.sub;
    }
    throw new Error("OIDC verification is not configured");
  }

  const { createRemoteJWKSet, jwtVerify } = await import("jose");
  jwks ??= createRemoteJWKSet(new URL(env.OIDC_JWKS_URL));
  const { payload } = await jwtVerify(token, jwks, {
    issuer: env.OIDC_ISSUER,
    audience: env.OIDC_AUDIENCE,
  });
  const userId = payload.oid || payload.sub;
  if (typeof userId !== "string" || !userId) {
    throw new Response(JSON.stringify({ message: "User identity is missing" }), {
      status: 401,
      headers: { "content-type": "application/json" },
    });
  }
  return userId;
}

export function errorResponse(error) {
  if (error instanceof Response) return error;
  console.error("BFF request failed", error);
  return Response.json({ message: "Request failed" }, { status: 500 });
}
