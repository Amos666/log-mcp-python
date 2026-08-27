"""STDIO 传输模式：逐行读 stdin、逐行写 stdout。

注意：应用日志必须走 stderr，绝不能污染 stdout 协议流。
"""

from __future__ import annotations

import logging
import sys

from log_mcp.mcp.handler import McpRequestHandler

logger = logging.getLogger(__name__)


class StdioServer:
    def __init__(self, request_handler: McpRequestHandler):
        self._handler = request_handler

    def start(self) -> None:
        logger.info("Starting stdio server")
        try:
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue

                logger.debug("Received request: %s", line)
                response = self._handler.handle_request(line)
                if response is None:
                    continue

                sys.stdout.write(response + "\n")
                sys.stdout.flush()
                logger.debug("Sent response: %s", response)
        except (BrokenPipeError, KeyboardInterrupt):
            logger.info("Stdio server interrupted")
        logger.info("Stdio server stopped")
