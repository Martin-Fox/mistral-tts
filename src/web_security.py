"""Origin checks before body reception and browser response protections."""
from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders, URL
from starlette.responses import JSONResponse


CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; "
    "media-src 'self' blob:; connect-src 'self'; object-src 'none'; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


def origin_identity(value):
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.path or parsed.query or parsed.fragment):
            return None
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == 'https' else 80)
        return parsed.scheme, parsed.hostname.lower(), port
    except ValueError:
        return None


def permitted_write(scope):
    headers = Headers(scope=scope)
    origins = headers.getlist('origin')
    if origins:
        if len(origins) != 1 or len(headers.getlist('host')) > 1:
            return False
        target = URL(scope=scope)
        expected = origin_identity(f'{target.scheme}://{target.netloc}')
        return expected is not None and origin_identity(origins[0]) == expected
    # Non-browser clients and same-origin JS without Origin explicitly opt in.
    # Cross-origin JS cannot add this non-simple header without a CORS preflight;
    # the application does not enable CORS. Never accept a bad Origin via fallback.
    return (headers.get('x-requested-with') == 'Booksmith'
            and headers.get('sec-fetch-site', 'none') in ('none', 'same-origin'))


class WebSecurity:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)

        async def send_protected(message):
            if message['type'] == 'http.response.start':
                headers = MutableHeaders(raw=message.setdefault('headers', []))
                headers['Content-Security-Policy'] = CONTENT_SECURITY_POLICY
                headers['X-Frame-Options'] = 'DENY'
                headers['X-Content-Type-Options'] = 'nosniff'
                headers['Referrer-Policy'] = 'no-referrer'
                if scope['path'] == '/' or scope['path'].startswith('/api/'):
                    headers['Cache-Control'] = 'no-store'
            await send(message)

        if scope['method'] not in ('GET', 'HEAD', 'OPTIONS') and not permitted_write(scope):
            return await JSONResponse({'detail': 'Invalid or missing request origin'}, status_code=403)(
                scope, receive, send_protected)
        await self.app(scope, receive, send_protected)
