from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import FileResponse


class SPAFallbackMiddleware(BaseHTTPMiddleware):
    """Intercept 404 from StaticFiles and serve index.html for SPA client-side routes.

    StaticFiles handles physical files normally; this middleware only kicks in
    when StaticFiles returns 404 — the request doesn't match any physical file
    and should be handled by the client-side router (e.g. React Router).

    Path traversal safety: we only ever read STATIC_DIR / "index.html" (a fixed
    path), never interpolate user input into filesystem paths.
    """

    def __init__(self, app, static_dir: Path, skip_prefixes=("/api/", "/playground")):
        super().__init__(app)
        self.static_dir = static_dir
        self.skip_prefixes = skip_prefixes

    async def dispatch(self, request, call_next):
        # API and playground requests pass through without fallback
        if any(request.url.path.startswith(p) for p in self.skip_prefixes):
            return await call_next(request)

        response = await call_next(request)
        if response.status_code == 404:
            index = self.static_dir / "index.html"
            if index.exists():
                return FileResponse(str(index))
        return response
