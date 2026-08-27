"""SSH 私钥执行通道（默认通道，与原 Java 版行为对齐）。

基于 paramiko 实现，每台服务器维护一个简易连接池：
- 空闲连接 LIFO 队列 + 总量上限（对应原版 commons-pool2 的 maxTotal）；
- 借出前健康检查（transport.is_active()），坏连接丢弃并重建；
- exec_command 使用 channel 超时，超时/失败降级为 CommandResult(-1, ...)。
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Optional

import paramiko

from log_mcp.config import AppConfig, ServerInfo
from log_mcp.executors.base import CommandExecutor
from log_mcp.models import CommandResult

logger = logging.getLogger(__name__)

_BORROW_WAIT_SECONDS = 10.0


class _ServerConnectionPool:
    """单台服务器的 SSH 连接池。"""

    def __init__(self, server: ServerInfo, max_size: int, connection_timeout_ms: int):
        self._server = server
        self._max_size = max(max_size, 1)
        self._connection_timeout_ms = connection_timeout_ms
        self._idle: queue.LifoQueue[paramiko.SSHClient] = queue.LifoQueue()
        self._created = 0
        self._lock = threading.Lock()

    def _is_alive(self, client: paramiko.SSHClient) -> bool:
        try:
            transport = client.get_transport()
            return transport is not None and transport.is_active()
        except Exception:  # noqa: BLE001
            return False

    def _connect(self) -> paramiko.SSHClient:
        server = self._server
        if not server.host:
            raise ValueError(
                f"server {server.name} 未配置 host，无法建立 SSH 连接"
            )
        if not server.private_key_path:
            raise ValueError(
                f"server {server.name} 未配置 privateKeyPath，SSH 通道仅支持私钥认证"
            )
        logger.debug(
            "Creating SSH connection to %s@%s:%s",
            server.username, server.host, server.port,
        )
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=server.host,
            port=server.port,
            username=server.username,
            key_filename=server.private_key_path,
            timeout=self._connection_timeout_ms / 1000.0,
            allow_agent=False,
            look_for_keys=False,
        )
        logger.info("SSH connection established to %s", server.name)
        return client

    def _discard(self, client: paramiko.SSHClient) -> None:
        with self._lock:
            self._created -= 1
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass

    def borrow(self) -> paramiko.SSHClient:
        """借出一个健康连接；池满且无空闲时等待其他线程归还。"""
        deadline = time.monotonic() + _BORROW_WAIT_SECONDS
        while True:
            # 1) 优先复用空闲连接（借出前健康检查，对应 testOnBorrow）
            try:
                client = self._idle.get_nowait()
            except queue.Empty:
                pass
            else:
                if self._is_alive(client):
                    return client
                self._discard(client)
                continue

            # 2) 池未满则新建
            with self._lock:
                can_create = self._created < self._max_size
                if can_create:
                    self._created += 1
            if can_create:
                try:
                    return self._connect()
                except Exception:
                    with self._lock:  # 创建失败，释放名额
                        self._created -= 1
                    raise

            # 3) 已满：等待空闲归还
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"SSH 连接池已满，等待空闲连接超时: {self._server.name}"
                )
            try:
                client = self._idle.get(timeout=min(remaining, 1.0))
            except queue.Empty:
                continue
            if self._is_alive(client):
                return client
            self._discard(client)

    def give_back(self, client: paramiko.SSHClient) -> None:
        if self._is_alive(client):
            self._idle.put(client)
        else:
            self._discard(client)

    def close_all(self) -> None:
        while True:
            try:
                client = self._idle.get_nowait()
            except queue.Empty:
                break
            self._discard(client)


class SshKeyExecutor(CommandExecutor):
    """paramiko + 私钥认证 + per-server 连接池。"""

    def __init__(self, config: AppConfig):
        self._config = config
        self._pools = {
            server.name: _ServerConnectionPool(
                server,
                max_size=int(config.ssh_pool.get("maxConnectionsPerServer", 3)),
                connection_timeout_ms=int(config.ssh_pool.get("connectionTimeout", 30000)),
            )
            for server in config.servers
            if server.connector == "ssh"
        }

    def execute(self, server_name: str, command: str, timeout_ms: int) -> CommandResult:
        pool = self._pools.get(server_name)
        if pool is None:
            return CommandResult(-1, "", f"Error: no ssh pool for server {server_name}")
        client: Optional[paramiko.SSHClient] = None
        try:
            client = pool.borrow()
            logger.debug("Executing command on %s: %s", server_name, command)
            _, stdout, stderr = client.exec_command(command, timeout=timeout_ms / 1000.0)
            stdout_str = stdout.read().decode("utf-8", errors="replace")
            stderr_str = stderr.read().decode("utf-8", errors="replace")
            exit_code = stdout.channel.recv_exit_status()
            return CommandResult(exit_code, stdout_str, stderr_str)
        except Exception as exc:  # noqa: BLE001 - 失败降级为结果，与原版一致
            logger.error("Error executing command on %s: %s", server_name, exc)
            return CommandResult(-1, "", f"Error: {exc}")
        finally:
            if client is not None:
                pool.give_back(client)

    def close(self) -> None:
        logger.info("Shutting down SSH connection pools")
        for pool in self._pools.values():
            pool.close_all()
