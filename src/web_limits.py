"""Bound generation requests before multipart parsing and bound background work."""
import asyncio
import tempfile
import threading

from starlette.responses import JSONResponse
from fastapi.routing import APIRoute

from src.core.resource_limits import ResourceLimits
from src.core.storage_retention import StorageBudgetExceeded

MAX_FORM_FIELDS = 32


class GenerationRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def parse_bounded_form(request):
            # The transport middleware has already bounded the entire body.
            # Override the framework's smaller default inline-field limit so
            # MAX_TEXT_CHARS can also be used for pasted text, not just files.
            await request.form(max_files=2, max_fields=MAX_FORM_FIELDS,
                               max_part_size=ResourceLimits.from_env().max_request_bytes)
            return await handler(request)
        return parse_bounded_form


class JobController:
    def __init__(self, running: int, queued: int):
        self.admission = threading.BoundedSemaphore(running + queued)
        self.workers = threading.BoundedSemaphore(running)

    async def run(self, function, **kwargs):
        while not self.workers.acquire(blocking=False):
            await asyncio.sleep(0.05)
        try:
            await function(**kwargs)
        finally:
            self.workers.release()


class GenerationRequestLimits:
    def __init__(self, app, controller, storage_check=None):
        self.app = app
        self.controller = controller
        self.storage_check = storage_check

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or (scope["path"] != "/api/generate" and not scope["path"].startswith("/api/resume/")) or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        controller = self.controller()
        if not controller.admission.acquire(blocking=False):
            return await JSONResponse({"detail": "Generation capacity is full"}, status_code=429,
                                      headers={"Retry-After": "5"})(scope, receive, send)
        try:
            if self.storage_check is not None:
                try:
                    await asyncio.to_thread(self.storage_check)
                except StorageBudgetExceeded as error:
                    return await JSONResponse({"detail": str(error)}, status_code=507)(scope, receive, send)
            limit = ResourceLimits.from_env().max_request_bytes
            headers = dict(scope["headers"])
            try:
                declared = int(headers.get(b"content-length", b"0"))
            except ValueError:
                declared = 0
            if declared > limit:
                return await JSONResponse({"detail": "Request exceeds MAX_REQUEST_BYTES"},
                                          status_code=413)(scope, receive, send)
            # Spool to disk before the framework parses multipart/form fields. This
            # also enforces the budget for chunked requests and forged Content-Length.
            with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as body:
                size = 0
                separators = 0
                urlencoded = headers.get(b"content-type", b"").split(b";", 1)[0].lower() == b"application/x-www-form-urlencoded"
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    data = message.get("body", b"")
                    size += len(data)
                    if size > limit:
                        return await JSONResponse({"detail": "Request exceeds MAX_REQUEST_BYTES"},
                                                  status_code=413)(scope, receive, send)
                    if urlencoded:
                        separators += data.count(b"&")
                        if separators >= MAX_FORM_FIELDS:
                            return await JSONResponse({"detail": "Too many form fields"},
                                                      status_code=413)(scope, receive, send)
                    body.write(data)
                    if not message.get("more_body", False):
                        break
                body.seek(0)
                replayed = False
                async def replay():
                    nonlocal replayed
                    if replayed:
                        return await receive()
                    chunk = body.read(65536)
                    more = body.tell() < size
                    replayed = not more
                    if replayed:
                        body.close()  # Do not retain the transport spool during long jobs.
                    return {"type": "http.request", "body": chunk, "more_body": more}
                # BackgroundTasks execute before this returns, so admission covers
                # upload, preflight, queued work and running work, including failures.
                await self.app(scope, replay, send)
        finally:
            controller.admission.release()
