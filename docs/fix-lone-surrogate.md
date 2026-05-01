# MemPalace MCP Server — Lone Surrogate 修复

## 问题描述

MemPalace MCP 服务器的写入功能（`mempalace_add_drawer`、`mempalace_diary_write`）在处理某些字符串参数时抛出 `UnicodeEncodeError: charmap codec can't encode character...` 错误。

## 根本原因

WorkBuddy 通过 MCP 协议传输字符串时，会注入 Python 非法的 Unicode 代理码点（lone surrogates），例如 `\udc95`、`\udcad` 等。这些字符：

- 在 Python 内部表示中合法，但无法编码到任何字符集（包括 UTF-8）
- 导致 SHA256 hash 计算失败：`UnicodeEncodeError: charmap codec can't encode character...`
- 导致 ChromaDB upsert/add 失败：ChromaDB 在序列化 metadata 时遇到 lone surrogate 报错

## 修复方案

在所有写入 ChromaDB 前，对所有字符串字段统一清理：

```python
def _clean(s):
    """Remove lone surrogates — ChromaDB rejects them in upsert/metadata."""
    return s.encode("utf-8", "surrogatepass").decode("utf-8", "ignore")
```

### 修复点

#### 1. `tool_add_drawer`（第 612-681 行）

- `content` 字段：在 `sanitize_content` 后清理
- `wing`、`room`、`added_by`：所有 metadata 字符串字段清理
- SHA256 hash 计算：使用 `surrogatepass` 编码避免报错

```python
# 第 617-619 行：定义 _clean 函数
def _clean(s):
    return s.encode("utf-8", "surrogatepass").decode("utf-8", "ignore")

# 第 625-626 行：清理 content 和 added_by
content = sanitize_content(content)
content = _clean(content)
added_by = _clean(added_by)

# 第 630-631 行：清理 wing 和 room
wing = _clean(wing)
room = _clean(room)

# 第 638 行：SHA256 hash 使用 surrogatepass
hashlib.sha256((wing + room + content).encode('utf-8', 'surrogatepass'))
```

#### 2. `tool_diary_write`（第 937-1017 行）

- `entry`、`topic`、`agent_name`、`wing`：所有字符串字段清理
- SHA256 hash 计算：使用 `surrogatepass` 编码

```python
# 第 946-948 行：定义 _clean 函数
def _clean(s):
    return s.encode("utf-8", "surrogatepass").decode("utf-8", "ignore")

# 第 953-954 行：清理 entry 和 topic
entry = sanitize_content(entry)
entry = _clean(entry)
topic = _clean(topic)

# 第 964-966 行：清理 agent_name、wing、topic
agent_name = _clean(agent_name)
wing = _clean(wing)
topic = _clean(topic)

# 第 974 行：SHA256 hash 使用 surrogatepass
hashlib.sha256(entry.encode('utf-8', 'surrogatepass'))
```

#### 3. 日志配置（第 75-83 行）

添加日志输出到文件，便于排查问题：

```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(r"C:\Users\SJC\mempalace\log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("mempalace_mcp")
```

## 技术细节

### Lone Surrogate 是什么？

Unicode 代理对（surrogate pair）用于在 UTF-16 中编码超出 U+FFFF 的字符：
- 高代理：U+D800 至 U+DBFF
- 低代理：U+DC00 至 U+DFFF

Lone surrogate 是指单独出现、没有配对的代理码点，在 UTF-8 编码中是非法的。

### 为什么 WorkBuddy 会注入 lone surrogate？

WorkBuddy 作为 MCP 客户端，在传输字符串时可能会在字符串中插入特殊的控制字符或标记，这些字符在某些情况下会产生 lone surrogate。

### surrogatepass 模式

Python 的 `str.encode('utf-8', 'surrogatepass')` 允许对代理码点进行编码而不报错，配合 `.decode('utf-8', 'ignore')` 可以安全地移除这些非法字符。

## 验证

修复后执行以下测试：

```bash
# 测试 add_drawer（带中文内容）
mcp__mempalace__mempalace_add_drawer  \
  --wing test  \
  --room unicode-test  \
  --content "测试中文内容：你好世界！🎉"

# 测试 diary_write（带 AAK 格式）
mcp__mempalace__mempalace_diary_write  \
  --agent_name test-agent  \
  --entry "SESSION:2026-04-27|fixed.lone-surrogate-bug|FIX:ssh"
```

## 影响范围

此修复解决了所有写入工具中的 Unicode 兼容性问题：

- ✅ `mempalace_add_drawer` — 通用抽屉写入
- ✅ `mempalace_diary_write` — Agent 日记写入

## 相关文件

- `D:\ProgramData\Python312\Lib\site-packages\mempalace\mcp_server.py` — 修复后的生产文件
- `D:\gitfork\mcp_server.py` — 修复后的开发副本
- `D:\gitfork\docs\fix-lone-surrogate.md` — 本文档

## 参考

- Python Unicode FAQ: https://docs.python.org/3/faq/extending.html#what-are-the-valid-forms-of-unicode-surrogate-pairs
- ChromaDB Issue #225: Lone surrogate handling in metadata serialization
