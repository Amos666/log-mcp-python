# Log-MCP (Python 版) 设计文档

> 本项目是开源项目 [caijianying/log-mcp](https://github.com/caijianying/log-mcp)（Java 21 实现）的 Python 重构版。
> 目标：**保持完全一致的 MCP 工具接口与协议行为**，同时把「日志获取通道」重构为**可插拔的多通道架构**（SSH 私钥直连 / 复用 pyinfra 连接 / 本地执行）。
> 本文档先于代码编写，作为实现依据；实现遵循设计思想重新开发，**不是逐行翻译 Java 代码**。

---

## 1. 背景

原 Log-MCP 是一个基于 MCP（Model Context Protocol）的远程日志查询服务：

- 通过 SSH 连接远程服务器，为 Claude Code 等 AI 助手提供日志查询能力；
- 支持 HTTP / STDIO 两种 MCP 传输模式；
- 提供 5 个工具：`list_servers`、`list_log_files`、`read_log_file`、`search_logs`、`tail_logs`；
- 核心思路：**在远端执行标准 POSIX 命令（grep / tail / sed / find）获取日志**，本地只做参数校验、命令拼装与结果解析。

原版限制：命令执行通道硬绑定 SSH（Apache MINA SSHD + Commons Pool2 连接池），无法复用团队已有的其他运维通道（例如 pyinfra 的主机连接体系）。

## 2. 原 Java 项目设计分析

```
LogMcpServer (main)
 ├─ config/ServerConfig        配置加载 (config.json + ${env} 占位符解析)
 ├─ pool/SshConnectionPool     SSH 连接池 (commons-pool2, per-server)
 │    └─ SshClientFactory      MINA SSHD 连接工厂 (私钥认证)
 ├─ service/
 │    ├─ CommandExecutor       借连接 → exec channel → CommandResult   ← 通道绑定 SSH
 │    ├─ LogService            业务编排：参数校验 → 命令拼装 → 执行 → 解析
 │    └─ ResultParser          grep 输出解析 (单/多文件模式, 上下文)
 ├─ tools/*                    5 个 MCP 工具 (Tool 接口: name/description/schema/execute)
 ├─ transport/
 │    ├─ McpRequestHandler     JSON-RPC 2.0 → initialize/tools/list/tools/call
 │    ├─ stdio/StdioServer     逐行 stdin/stdout
 │    └─ http/HttpServer       Undertow, POST /mcp, GET 健康检查
 ├─ security/                  参数校验 / 路径防穿越 / Shell 转义
 └─ util/                      日期工具 / 日志文件名模式解析 ({level}/{date}/{seq})
```

**值得继承的设计思想**：

1. **命令统一**：所有日志操作归一为一段在目标机执行的 shell 命令，业务语义（文件命名模式、级别、日期范围）全部体现在命令拼装层，远端只需要一个普通 shell。
2. **分层清晰**：工具层（MCP 接口）→ 服务层（业务+命令）→ 执行层（通道）→ 解析层（输出→结构化数据）。
3. **安全前置**：所有用户输入在拼命令之前经过校验/转义（防注入、防路径穿越、防资源滥用）。
4. **声明式工具**：Tool = name + description + JSON Schema + execute，天然适配 `tools/list`。

**需要重构的点**：

1. `CommandExecutor` 直接依赖 `SshConnectionPool`，通道不可替换；
2. 连接池与通道实现耦合（池应下沉为某一种通道的实现细节）；
3. 全部服务器只有一种连接方式。

## 3. Python 版总体架构

```
┌────────────────────────────────────────────────────────────────┐
│  MCP 传输层  mcp/                                                │
│    stdio_server.py   http_server.py                             │
│    handler.py  (JSON-RPC 2.0: initialize / tools/list / tools/call)│
├────────────────────────────────────────────────────────────────┤
│  工具层  tools.py                                                │
│    list_servers list_log_files read_log_file search_logs tail_logs│
├────────────────────────────────────────────────────────────────┤
│  服务层  service/                                                │
│    log_service.py   业务编排 (校验→拼命令→执行→解析)               │
│    commands.py      ★ 统一命令构建 (grep/tail/sed/find, 全通道唯一) │
│    parser.py        grep/tail/find 输出解析                       │
├────────────────────────────────────────────────────────────────┤
│  执行通道层  executors/  ★ 核心重构点                              │
│    base.py     CommandExecutor 抽象 (server, command, timeout)   │
│                 → CommandResult(exit_code, stdout, stderr)      │
│    router.py   ExecutorRouter: 按 server.connector 路由           │
│    ssh_key.py  paramiko + 私钥 + per-server 连接池 (兼容原版)      │
│    pyinfra.py  复用 pyinfra Inventory/Host 连接执行                │
│    local.py    本地 subprocess (开发/测试/单机)                    │
├────────────────────────────────────────────────────────────────┤
│  基础设施  config.py  models.py  security/  util.py               │
└────────────────────────────────────────────────────────────────┘
```

与原版包结构对照：

| Java 原版 | Python 版 | 说明 |
|---|---|---|
| `LogMcpServer` | `server.py` + `__main__.py` | 应用组装与生命周期 |
| `config/` | `config.py` | dataclass 模型 + `${env}` 占位符解析 |
| `model/` | `models.py` | `CommandResult` / `LogEntry` / 各请求模型 |
| `pool/` | `executors/ssh_key.py`（内置池） | 连接池下沉为通道实现细节 |
| `protocol/` + `transport/McpRequestHandler` | `mcp/handler.py` | JSON-RPC 2.0 编解码与分发 |
| `transport/stdio` `transport/http` | `mcp/stdio_server.py` `mcp/http_server.py` | 传输模式 |
| `security/` | `security/` | 校验 / 转义 / 路径防护 |
| `service/` | `service/` | 命令构建、解析、业务编排 |
| `tools/` | `tools.py` | 5 个 MCP 工具（声明式注册） |
| `util/` | `util.py` | 日期范围 / 文件名模式 / 尺寸格式化 |

## 4. 核心设计：可插拔执行通道（Executor SPI）

### 4.1 抽象接口

```python
class CommandExecutor(ABC):
    """命令执行通道：把一段 shell 命令送到目标机器执行，拿回统一结果。"""

    @abstractmethod
    def execute(self, server_name: str, command: str, timeout_ms: int) -> CommandResult: ...

    def close(self) -> None: ...
```

约定（对齐原版 `CommandExecutor` 语义）：

- 输入只有 `(server_name, command, timeout_ms)`——**命令文本全通道唯一**，由 `service/commands.py` 统一生成，通道不掺入任何业务语义；
- 输出统一 `CommandResult(exit_code, stdout, stderr)`；执行失败（连不上/超时）不抛异常，返回 `exit_code=-1`、错误信息进 `stderr`（与原版行为一致，业务层据此返回空结果）；
- 通道自身管理连接生命周期（池、复用、健康检查、关闭钩子）。

### 4.2 通道路由（ExecutorRouter）

每台服务器可在配置中独立指定通道：`"connector": "ssh" | "pyinfra" | "local"`（默认 `ssh`，**对原版 config.json 完全向后兼容**）。

`ExecutorRouter` 同样实现 `CommandExecutor` 接口，按 `server.connector` 分发到对应通道实例。`LogService` 只面向 `CommandExecutor` 抽象编程，对后端拓扑无感知。

### 4.3 通道注册表

`executors/registry.py` 维护 `name → factory(config)` 注册表，`create_executors(config)` 为配置中出现过的每种 connector 懒构造一个实例并装配 Router。新增通道（docker exec、跳板机、Agent 等）只需实现 `CommandExecutor` 并注册，**不改任何业务代码**。

### 4.4 内置三种通道

| 通道 | 实现要点 | 适用场景 |
|---|---|---|
| `ssh` (ssh_key) | paramiko 私钥认证；per-server 连接池（LIFO 空闲队列 + 总量上限 + 借出前健康检查 `transport.is_active()`，坏连接丢弃重建）；`exec_command` + channel 超时 | 与原版等价的默认通道 |
| `pyinfra` | 按配置构造 pyinfra `Inventory`（host spec + `ssh_user/ssh_port/ssh_key` 等数据），`State + connect_all` 建立连接；执行走 `host.run_shell_command(command, _timeout=…)`，从 `CommandOutput.stdout_lines/stderr_lines` 还原结果 | 团队已有 pyinfra 主机资产/连接配置，直接复用 |
| `local` | `subprocess.run(["sh", "-c", command], timeout=…)` | 开发调试、单机部署、集成测试 |

> pyinfra 通道对 pyinfra 为**可选依赖**（`pip install log-mcp-python[pyinfra]`），仅在被使用时 import，缺失时给出明确错误提示。

## 5. 模块设计

### 5.1 config.py

- dataclass：`ServerInfo`（name/host/port/username/private_key_path/log_root_path/description/is_default + **connector / pyinfra_host / pyinfra_data**）、`AppConfig`（servers/log_levels/log_file_pattern/ssh_pool/query_defaults 及带默认值的取值方法）。
- 加载顺序：`LOG_CONFIG` 环境变量 → `--config` 参数 → 默认 `config.json`（与原版 `LOG_CONFIG`/`log.config` 一致）。
- `${VAR}` 占位符解析：正则替换，取值来源为环境变量（原版先系统属性后环境变量，Python 版统一为环境变量）。

### 5.2 models.py

- `CommandResult(exit_code, stdout, stderr)` + `is_success`；
- `LogEntry(server, file, lineNumber, content, contextBefore, contextAfter)` + `to_dict()`；
- 各工具请求模型（`SearchLogsRequest` 等，dataclass，带默认值）。

### 5.3 security/

- `validators.py`：级别（info/warn/error/debug，大小写不敏感）、日期（YYYY-MM-DD 且真实日历日期）、keyword（非空、≤500 字符）、maxResults（正数且 ≤ 上限）、contextLines（0~10）、文件路径（非空、无 `..`、`.log` 结尾、拼接归一化后必须落在 logRootPath 内 —— 防路径穿越）。
- `shell.py`：`quote()`（等价原版单引号转义，直接采用 `shlex.quote`）；`escape_for_grep(keyword, use_regex)`——**非正则模式**下拒绝 shell 元字符 `;&|`$(){}[]<>` 及换行（提示改用正则模式），正则模式单引号包裹。

### 5.4 service/commands.py（命令统一层 ★）

| 操作 | 命令模板（与原版语义一致） |
|---|---|
| 搜索 | `grep -i -n -F|-E [-A n -B n] -- '<keyword>' '<f1>' '<f2>' … 2>/dev/null \|\| true` |
| 尾部 | `tail -n <lines> -- '<path>'` |
| 读取 | `sed -n '<start>,<end>p' -- '<path>'` |
| 列文件 | `find '<levelDir>' -name '*.log' -type f -printf '%p\|%s\|%TY-%Tm-%Td %TH:%TM:%TS\n' 2>/dev/null \|\| true` |

要点：文件路径与关键词一律经 `security.shell.quote()` 转义后再入命令；缺失文件容错（`2>/dev/null || true`）由命令本身保证，通道无需感知。

### 5.5 service/parser.py

- `parse_grep_output`：识别四种 grep 行格式（单文件 `N:content`/`N-content`、多文件 `F:N:content`/`F-N-content`），`--` 分隔符重置上下文，维护 before 缓冲与 after 计数，达 `maxResults` 截断（复刻原版 `ResultParser` 算法）。
  **改进点**：由于命令由本服务统一构建，grep 的输入文件列表是已知的，多文件行优先按**已知文件前缀做确定性匹配**，仅在无文件列表时回退到原版的贪婪正则启发式——避免日志内容中的时间戳（`04:22:28` 含冒号/连字符）干扰行格式识别（原版存在把上下文行误判为命中行的问题）。
- `parse_lines`：按 `\n` 切分 stdout（tail/read 共用）。
- `parse_find_output`：按 `|` 三段拆分 → `{path, size, lastModified, level}`，path 去掉 logRootPath 前缀，size 人性化（B/KB/MB）。

### 5.6 service/log_service.py

`LogService(executor, config)` 五个业务方法，流程统一为：

```
解析 server (缺省→default 服务器) → 参数校验 → 文件名模式/日期推导 → 命令构建 → executor.execute → 解析 → 组装响应 dict
```

文件名模式推导（`util.FilePatternResolver`）：`{level}/log-{level}-{date}.{seq}.log`，`{seq}` 枚举 0–9，日期为起止区间逐日展开（默认今天）——与原版一致。

### 5.7 tools.py

声明式注册（Python 版将 5 个小类合并为单文件）：

```python
@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[[dict], Any]
```

工具名、参数 schema（属性、required）、返回结构与原版 README 契约逐字段对齐。

### 5.8 mcp/handler.py

手写轻量 JSON-RPC 2.0（与原版一致，不引入 MCP SDK，保证行为逐字节对齐）：

| method | 行为 |
|---|---|
| `initialize` | `{"protocolVersion":"2025-11-25","serverInfo":{"name":"log-mcp","version":"1.0.0"},"capabilities":{"tools":{}}}` |
| `tools/list` | `{"tools":[{name,description,inputSchema}…]}` |
| `tools/call` | 取 `params.name/arguments` 执行工具；成功 → `result.content=[{type:"text",text:JSON(业务结果)}]`；工具不存在 → `-32602`；执行异常 → `-32603` |
| `notifications/initialized` | 返回 `None`（无响应体；stdio 丢弃 / http 202） |
| 其他 | `-32601 Method not found` |
| 解析失败 | `-32603 Internal error` |

### 5.9 mcp/stdio_server.py / http_server.py

- **stdio**：逐行读 stdin、逐行写 stdout 并 flush；**所有应用日志走 stderr**，绝不污染协议流。
- **http**：标准库 `ThreadingHTTPServer`（替代 Undertow）；`POST /` 与 `POST /mcp` 处理 JSON-RPC；`GET` 返回 `{"status":"ok","service":"log-mcp"}` 健康检查；通知类（无响应）返回 202；其余方法 405。端口默认 8892（`--port` / `SERVER_PORT`）。

### 5.10 server.py / __main__.py

组装顺序（对应原 main）：加载配置 → 创建通道 Router → LogService → McpRequestHandler → 按传输模式启动（`TRANSPORT_MODE` 环境变量或 `--transport`，默认 stdio）→ 注册退出钩子关闭通道。

## 6. 配置设计

```jsonc
{
  "servers": [
    // ① SSH 私钥通道（与原版字段完全兼容，可不写 connector）
    {
      "name": "local-server",
      "connector": "ssh",
      "host": "192.168.5.169",
      "port": 22,
      "username": "root",
      "privateKeyPath": "${SSH_KEY_PATH}",
      "logRootPath": "/home/docker/logs/app/",
      "description": "169测试服务器",
      "default": true
    },
    // ② pyinfra 通道：直接给 host/user/key（等价信息由 pyinfra 建连）
    {
      "name": "pyinfra-server",
      "connector": "pyinfra",
      "host": "192.168.5.9",
      "port": 22,
      "username": "root",
      "privateKeyPath": "${SSH_KEY_PATH}",
      "logRootPath": "/home/web/docker/logs/app/",
      "description": "复用pyinfra连接的5.9服务器"
    },
    // ③ pyinfra 通道：直接复用已有主机 spec + 透传数据
    {
      "name": "inventory-server",
      "connector": "pyinfra",
      "pyinfraHost": "root@192.168.5.20:22",
      "pyinfraData": { "ssh_key": "/root/.ssh/id_rsa" },
      "logRootPath": "/var/log/app/",
      "description": "已有pyinfra资产"
    },
    // ④ 本地通道（开发/测试）
    {
      "name": "dev-local",
      "connector": "local",
      "logRootPath": "/tmp/logs/",
      "description": "本机日志",
      "default": true
    }
  ],
  "logLevels": ["info", "warn", "error", "debug"],
  "logFilePattern": "{level}/log-{level}-{date}.{seq}.log",
  "sshPool":   { "maxConnectionsPerServer": 3, "connectionTimeout": 30000, "idleTimeout": 300000 },
  "queryDefaults": { "maxResults": 100, "maxResultsLimit": 1000, "searchTimeout": 30000, "defaultTailLines": 50 }
}
```

规则：`connector` 缺省为 `ssh`；原版配置文件**原样可用**。

## 7. MCP 接口契约（与原版一致）

| 工具 | 参数 | 返回 |
|---|---|---|
| `list_servers` | — | `{servers:[{name,host,description,isDefault,status}]}` |
| `list_log_files` | server?, level?, startDate?, endDate? | `{server,files:[{path,size,lastModified,level}],totalFiles}` |
| `read_log_file` | **filePath**, server?, startLine?, endLine?, maxLines? | `{server,file,lines,totalLines}` |
| `search_logs` | **keyword**, server?, levels?(默认[debug,info]), startDate?, endDate?, useRegex?, contextLines?(默认3), maxResults? | `{results:[{server,file,lineNumber,content,contextBefore,contextAfter}],summary:{totalMatches,serversQueried,serversFailed,searchTime}}` |
| `tail_logs` | server?, level?(默认info), lines?(默认50) | `{server,file,lines,totalLines}` |

行为细节对齐：日期默认今天；读取行区间 `startLine..startLine+99`（无 endLine/maxLines 时）；`tools/call` 结果为 JSON 字符串文本节点。

## 8. 安全设计

1. **输入校验前置**：级别/日期/长度/数量约束全部在拼命令前完成；
2. **命令注入防护**：关键词与路径全部 `shlex.quote` 单引号包裹；非正则搜索关键词出现 shell 元字符直接拒绝（与原版策略一致）；
3. **路径穿越防护**：`filePath` 禁 `..`、必须 `.log` 结尾、归一化后必须位于 `logRootPath` 之内；
4. **资源保护**：maxResults / maxReadLines 上限、搜索超时（透传到通道执行超时）；
5. **认证**：SSH 仅私钥认证（不落密码），私钥路径支持环境变量注入，配置文件不落敏感值。

## 9. 并发与生命周期

- stdio 模式：单线程顺序处理请求（与原版一致）；
- http 模式：`ThreadingHTTPServer` 每请求一线程；SSH 池内部以锁保护创建/归还，paramiko 连接在池中同一时刻仅被一个请求借用；
- 退出钩子（SIGTERM/KeyboardInterrupt）统一调用 `executor.close()` 关闭全部连接（pyinfra 通道调用 `disconnect_all`）。

## 10. 依赖

- Python ≥ 3.10，仅核心依赖 `paramiko`（ssh 通道）；
- 可选依赖：`pyinfra`（pyinfra 通道）、`pytest`（测试）；
- MCP 协议层零依赖（标准库 json / http.server / sys.stdin）。

## 11. 测试策略

| 层 | 测试 | 说明 |
|---|---|---|
| security | validators / shell 转义 | 恶意输入、路径穿越、元字符 |
| service | commands / parser / pattern | 命令模板快照、grep 四种行格式与上下文算法 |
| mcp | handler | JSON-RPC 各 method、错误码、通知无响应 |
| 集成 | local 通道全链路 | 临时目录造日志树 → `tools/call` 全部 5 工具 → 断言结构化结果（不依赖任何真实 SSH） |

## 12. 目录结构

```
log-mcp-python/
├── docs/DESIGN.md                 # 本文档
├── pyproject.toml
├── config.example.json
├── README.md
├── log_mcp/
│   ├── __init__.py                # 版本信息
│   ├── __main__.py                # CLI 入口 (python -m log_mcp / log-mcp)
│   ├── server.py                  # 应用组装
│   ├── config.py                  # 配置模型与加载
│   ├── models.py                  # CommandResult/LogEntry/请求模型
│   ├── util.py                    # 日期/文件名模式/格式化
│   ├── security/
│   │   ├── validators.py
│   │   └── shell.py
│   ├── executors/                 # ★ 可插拔执行通道
│   │   ├── base.py                #   CommandExecutor 抽象
│   │   ├── registry.py            #   注册表 + ExecutorRouter + 工厂
│   │   ├── ssh_key.py             #   paramiko + 连接池
│   │   ├── pyinfra_exec.py        #   pyinfra 复用
│   │   └── local.py               #   本地 subprocess
│   ├── service/
│   │   ├── commands.py            # ★ 统一命令构建
│   │   ├── parser.py
│   │   └── log_service.py
│   ├── tools.py                   # 5 个 MCP 工具
│   └── mcp/
│       ├── handler.py             # JSON-RPC 2.0 / MCP 方法分发
│       ├── stdio_server.py
│       └── http_server.py
└── tests/
    ├── test_validators.py
    ├── test_shell.py
    ├── test_commands.py
    ├── test_parser.py
    ├── test_handler.py
    └── test_integration_local.py
```
