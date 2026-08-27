"""HTTP 传输模式：POST / 与 /mcp 处理 JSON-RPC，GET 健康检查。

基于标准库 ThreadingHTTPServer（对应原版 Undertow 的角色）。
"""

from __future__ import annotations

import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from log_mcp.mcp.handler import McpRequestHandler

logger = logging.getLogger(__name__)

_HEALTH_BODY = '{"status":"ok","service":"log-mcp"}'
_INTERNAL_ERROR_BODY = (
    '{"jsonrpc":"2.0","id":null,"error":{"code":-32603,"message":"Internal server error"}}'
)


class _McpHttpHandler(BaseHTTPRequestHandler):
    server_version = "log-mcp"

    # 由 HttpServer 注入
    mcp_handler: McpRequestHandler

    def do_GET(self) -> None:  # noqa: N802 - http.server 约定
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._end_json(_HEALTH_BODY.encode("utf-8"))

    def _method_not_allowed(self) -> None:
        self.send_error(405, "Method Not Allowed")

    do_PUT = do_DELETE = do_PATCH = _method_not_allowed

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path not in ("/", "/mcp"):
            self.send_error(404, "Not Found")
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8") if length else ""
        except (ValueError, UnicodeDecodeError) as exc:
            logger.error("Error reading request body: %s", exc)
            self._send_internal_error()
            return

        try:
            logger.debug("Received HTTP request: %s", body)
            response = self.mcp_handler.handle_request(body)
        except Exception as exc:  # noqa: BLE001
            logger.error("Error handling HTTP request", exc_info=True)
            self._send_internal_error()
            return

        if response is None:
            # 通知类请求：无需响应体
            self.send_response(202)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self._end_json(response.encode("utf-8"))

    def _send_internal_error(self) -> None:
        self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self._end_json(_INTERNAL_ERROR_BODY.encode("utf-8"))

    def _end_json(self, payload: bytes) -> None:
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args) -> None:  # 静默默认访问日志，走应用日志
        logger.debug("http: " + fmt, *args)


class HttpServer:
    def __init__(self, request_handler: McpRequestHandler, port: int):
        self._request_handler = request_handler
        self._port = port
        self._server: ThreadingHTTPServer | None = None

    def start(self) -> None:
        handler_cls = type(
            "BoundMcpHttpHandler", (_McpHttpHandler,), {"mcp_handler": self._request_handler}
        )
        self._server = ThreadingHTTPServer(("0.0.0.0", self._port), handler_cls)
        logger.info("HTTP server started on port %s (paths: /, /mcp)", self._port)
        try:
            self._server.serve_forever()
        finally:
            self._server.server_close()
            logger.info("HTTP server stopped")

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            logger.info("HTTP server stopped")
