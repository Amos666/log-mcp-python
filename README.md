# log-mcp-python

基于 MCP（Model Context Protocol）的远程日志查询服务，Python 实现。

本项目是开源 Log-MCP（Java 版）的重新设计与实现：**对外提供完全一致的 MCP 工具接口**（JSON-RPC 2.0、STDIO / HTTP 两种传输模式），对内按 Python 习惯重构了整体架构，并将「日志获取方式」抽象为**可插拔的执行通道**——获取日志的具体命令统一由服务构建，只有执行命令的通道多种多样。

## 特性

- **接口兼容**：与原 Java 版一致的 5 个 MCP 工具（`search_logs` / `tail_logs` / `read_log_file` / `list_log_files` / `list_servers`），输入输出契约对齐。
- **可插拔执行通道**：
  - `ssh` — SSH 私钥直连（paramiko，带连接池与自动重连）
  - `pyinfra` — 复用已有的 pyinfra 主机资产（支持 `@local`、`root@host:22` 等主机 spec）
  - `local` — 本机执行（开发 / 测试）
- **命令统一构建**：所有日志操作都归一为一段在目标机执行的 shell 命令（`grep -n -A -B` / `tail -n` / `sed -n` / `find`），与执行通道解耦——新增通道只需实现 `CommandExecutor.execute()`。
- **安全**：参数校验、相对路径校验、危险字符检测、与原版一致的 shell 单引号转义。
- **零重量依赖**：核心仅依赖 `paramiko`；`pyinfra` 为可选依赖，仅在用到 pyinfra 通道时安装。

## 架构

```
MCP 客户端（AI 助手 / IDE）
        │  JSON-RPC 2.0
        ▼
mcp/            传输与协议层（stdio_server / http_server / handler）
        ▼
tools.py        5 个工具的声明式定义（名称 + JSON Schema + 处理函数）
        ▼
service/        业务编排层（参数校验 → 文件推导 → 命令构建 → 解析）
        ▼
executors/      可插拔执行通道（ssh_key / pyinfra_exec / local + registry）
        ▼
目标服务器上的 shell 命令（grep / tail / sed / find）
```

详细设计见 [docs/DESIGN.md](docs/DESIGN.md)。

## 安装

```bash
pip install .            # 核心功能（ssh + local 通道）
pip install .[pyinfra]   # 需要 pyinfra 通道时
pip install .[dev]       # 运行测试
```

## 配置

参考 [config.example.json](config.example.json)。与原 Java 版的 `config.json` 结构兼容，并做了以下扩展：

- 每台服务器通过 `connector` 字段独立指定执行通道：`ssh`（默认）/ `pyinfra` / `local`
- pyinfra 通道支持 `pyinfraHost`（完整主机 spec，如 `root@192.168.5.20:22` 或 `@local`）与 `pyinfraData`（透传给 pyinfra 的主机数据，如 `ssh_key`）
- 字符串支持 `${VAR}` 环境变量占位符（未定义则原样保留）

```json
{
  "servers": [
    {
      "name": "ssh-server",
      "connector": "ssh",
      "host": "192.168.5.169",
      "port": 22,
      "username": "root",
      "privateKeyPath": "${SSH_KEY_PATH}",
      "logRootPath": "/home/docker/logs/myapp/",
      "default": true
    },
    {
      "name": "pyinfra-server",
      "connector": "pyinfra",
      "pyinfraHost": "root@192.168.5.20:22",
      "pyinfraData": { "ssh_key": "/root/.ssh/id_rsa" },
      "logRootPath": "/var/logs/app/"
    },
    {
      "name": "dev-local",
      "connector": "local",
      "logRootPath": "/tmp/logs/"
    }
  ],
  "logLevels": ["info", "warn", "error", "debug"],
  "logFilePattern": "{level}/log-{level}-{date}.{seq}.log"
}
```

关键字段说明：

| 字段 | 说明 |
| --- | --- |
| `connector` | 执行通道：`ssh` / `pyinfra` / `local` |
| `logRootPath` | 日志根目录（相对路径校验的基准） |
| `logFilePattern` | 日志文件命名模式，`{level}`/`{date}`/`{seq}` 占位 |
| `sshPool` | SSH 连接池（连接数上限 / 超时 / 重试） |
| `queryDefaults` | 查询默认值与上限（maxResults / maxReadLines / contextLines 等） |

## 运行

```bash
# STDIO 模式（MCP 客户端拉起，默认）
log-mcp --config config.json

# HTTP 模式（独立部署，端口默认 8892，路径 / 与 /mcp，健康检查 GET /health）
log-mcp --config config.json --transport http --port 8892
```

也支持环境变量：`LOG_CONFIG`、`TRANSPORT_MODE`、`SERVER_PORT`。

接入 MCP 客户端（以 HTTP 模式为例）：

```json
{
  "mcpServers": {
    "log-mcp": {
      "url": "http://your-host:8892/mcp"
    }
  }
}
```

STDIO 模式接入：

```json
{
  "mcpServers": {
    "log-mcp": {
      "command": "log-mcp",
      "args": ["--config", "/path/to/config.json"]
    }
  }
}
```

## MCP 工具

| 工具 | 说明 |
| --- | --- |
| `search_logs` | 按关键字（可选正则）跨日期、跨级别搜索日志，带前后上下文 |
| `tail_logs` | 获取指定级别的最新 N 行日志 |
| `read_log_file` | 读取指定日志文件的行区间 |
| `list_log_files` | 列出服务器上可用的日志文件（大小 / 修改时间） |
| `list_servers` | 列出所有已配置的服务器 |

调用示例（HTTP）：

```bash
curl -s -X POST http://127.0.0.1:8892/mcp -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
       "params":{"name":"search_logs","arguments":{"keyword":"ERROR","levels":["error","info"]}}}'
```

## 测试

```bash
python -m pytest tests/ -q
```

测试覆盖：参数/路径校验、shell 转义、命令构建、grep 输出解析（含已知文件确定性解析）、JSON-RPC 协议处理，以及 local / pyinfra(`@local`) 两个通道的端到端集成测试（共 100 个用例）。

## License

Apache-2.0
