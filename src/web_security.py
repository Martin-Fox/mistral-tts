"""Origin checks before body reception, trusted-proxy client resolution and
browser response protections."""
import ipaddress
import os
from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders, URL
from starlette.responses import JSONResponse

# Bound the accepted X-Forwarded-For chain; longer chains are ignored.
MAX_FORWARDED_ENTRIES = 16


def trusted_proxy_networks(value=None):
    """Parse TRUSTED_PROXY_CIDRS (comma-separated CIDRs); empty/unset trusts nobody."""
    raw = os.getenv('TRUSTED_PROXY_CIDRS', '') if value is None else value
    networks = []
    for item in raw.split(','):
        item = item.strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            raise ValueError(
                'TRUSTED_PROXY_CIDRS must be a comma-separated list of IP networks (e.g. "10.0.0.0/8, 127.0.0.1/32")'
            ) from None
    return networks


def forwarded_client_address(value, networks):
    """Return the rightmost X-Forwarded-For entry that is not a trusted proxy.

    Entries must be plain IP addresses; anything malformed fails closed (None),
    as do chains longer than MAX_FORWARDED_ENTRIES.
    """
    entries = [entry.strip() for entry in value.split(',')]
    if not entries or len(entries) > MAX_FORWARDED_ENTRIES:
        return None
    addresses = []
    for entry in entries:
        try:
            addresses.append(ipaddress.ip_address(entry))
        except ValueError:
            return None
    for address in reversed(addresses):
        if not any(address in network for network in networks):
            return str(address)
    # Every hop is a trusted proxy; the leftmost entry is still inside them.
    return str(addresses[0])


class TrustedProxyHeaders:
    """Rewrite scope["client"] from X-Forwarded-For only when the direct peer
    is inside TRUSTED_PROXY_CIDRS. Without configuration no header is trusted,
    so client-supplied forwarding headers cannot spoof the login limiter."""

    def __init__(self, app, networks=lambda: trusted_proxy_networks()):
        self.app = app
        self.networks = networks

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            client = scope.get('client')
            if client:
                networks = self.networks()
                if networks:
                    try:
                        peer = ipaddress.ip_address(client[0])
                    except ValueError:
                        peer = None
                    if peer is not None and any(peer in network for network in networks):
                        headers = Headers(scope=scope)
                        forwarded = headers.getlist('x-forwarded-for')
                        # Duplicate forwarding headers are ambiguous; ignore them.
                        if len(forwarded) == 1:
                            address = forwarded_client_address(forwarded[0], networks)
                            if address is not None:
                                scope['client'] = (address, client[1])
        await self.app(scope, receive, send)


CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; "
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
