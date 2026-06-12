from fastapi import HTTPException, Request


def extract_gateway_user_id(request: Request) -> str:
    """Extract verified user_id from AgentArts Gateway injected header.

    Production (CUSTOM_JWT): Gateway validates JWT then injects this header.
    It is guaranteed to be present and trustworthy.
    Development (key_auth or no Gateway): Manually inject this header to
    simulate identity.

    Raises:
        HTTPException(401): Fail-closed when header is missing in production.
    """
    user_id = request.headers.get("X-HW-AgentGateway-User-Id", "").strip()
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Missing X-HW-AgentGateway-User-Id header",
        )
    return user_id
