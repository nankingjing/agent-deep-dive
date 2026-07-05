# Hermes Agent 上下文压缩系统：三层 Bug 深度分析

> 作者：黄云龙 (nankingjing)  
> 项目：Hermes Agent (NousResearch) — 核心 Contributor  
> 分析对象：`agent/conversation_compression.py` + `agent/context_compressor.py` + `agent/model_metadata.py`

---

## 为什么写这篇文章

我在 Hermes Agent 的上下文压缩（Context Compression）系统中发现并修复了多个 bug。回看时发现这些 bug 彼此相关——它们揭示了同一个系统性问题：**压缩系统的"配置 → 模型检测 → 运行时"三层调用链缺乏类型安全边界**。

这篇文章追踪了 `auxiliary.compression.context_length` 一个配置值如何穿过三层代码、在每个层级被不同地解释、最终在运行时引发完全不同的故障。

---

## 背景：Agent 上下文压缩的作用

LLM Agent 在长对话中会积累大量消息（几百条消息、几十万 tokens）。上下文压缩（compression）的功能是：当 token 数超过阈值时，用一个辅助模型将早期对话总结成一两句话，释放被占用的上下文窗口。

关键流程：
```
用户设置 config.yaml
  → agent_init.py 读取配置
    → conversation_compression.py 检查压缩模型可行性（check_compression_model_feasibility）
      → model_metadata.py 检测辅助模型的实际 context window
        → context_compressor.py 运行时执行压缩
```

---

## Bug 1：`_db_persisted` Marker 传播导致 Session Amnesia

### 现象
Gateway 重启后，所有压缩过的会话丢失了 transcript——用户打开历史 session 看到的是空白。

### 追踪

在 `conversation_compression.py` 的 rotation 流程中，压缩后的消息列表通过 `_flush_messages_to_session_db()` 写入新的 child session。但这个函数在写入前会检查每条消息上是否存在 `_db_persisted` marker：

```python
# 简化的逻辑
for msg in compressed_messages:
    if getattr(msg, '_db_persisted', False):
        continue  # 跳过！不写入！
    # 写入 session DB
```

问题出在 `_fresh_compaction_message_copy()` 中。这个消息复制函数从缓存的 gateway incremental flush 中浅拷贝了消息对象——连 `_db_persisted` marker 也一起拷贝过来。下游的 session DB 写入器看到所有消息都标记为"已持久化"，跳过了全部写入。

### 为什么难发现

1. **只在 gateway 重启后复现**——因为内存中的消息在重启后需要从 session DB 重新加载
2. **marker 是内部状态**——不是用户可见的字段，只在深层调用链中传递
3. **浅拷贝的副作用**——Python 的 `copy()` 默认浅拷贝，把不该传播的内部状态也复制了

### 修复

在 `_fresh_compaction_message_copy()` 中显式 strip `_db_persisted` marker：

```python
def _fresh_compaction_message_copy(msg):
    copy = msg.copy()
    copy.pop('_db_persisted', None)
    return copy
```

**kshitijk4poor（项目 Top Contributor）后续在这个修复之上加了 follow-up**：`enforce marker-strip invariant with a single terminal sweep`——在我的基础上把 marker 清理统一到压缩管道的最后一个阶段执行。

---

## Bug 2：`auxiliary.compression.context_length` 触发 Auto-Lower，导致每轮都压缩

### 现象

用户设置 `auxiliary.compression.context_length: 128000`（deepseek-v4-flash 的实际 context window）后，长会话（~734 条消息、~383K tokens）中压缩在**每一轮**都触发，而不是只在超过阈值时才触发。

### 追踪

这个配置值经过了三个函数：

**第一层：`model_metadata.py::get_model_context_length()`**

```python
# 配置覆盖直接返回——"用户最了解自己的模型"
if config_context_length is not None:
    return config_context_length  # 返回 128000
```

**第二层：`conversation_compression.py::_check_compression_model_feasibility()`**

```python
aux_context = get_model_context_length(
    aux_model, 
    config_context_length=getattr(agent, '_aux_compression_context_length_config', None)
)
# aux_context = 128000

threshold = agent.context_compressor.threshold_tokens  # 400000

if aux_context < threshold:  # 128000 < 400000 → True!
    # Auto-lower：自动降低 session 压缩阈值
    agent.context_compressor.threshold_tokens = aux_context  # 128000!
```

**第三层：运行时**

压缩阈值变成了 128000——只要 session 超过 128000 tokens（在长会话中几乎是每一轮），就会触发压缩。

### 为什么难发现

1. **Auto-lower 本身是合理的设计**——当辅助模型比主模型小时，降低阈值确保压缩能正常工作
2. **但用户设置的值被当成了"模型真实能力"**——用户设 128000 是因为那就是模型的真实 context window，不是为了降低阈值
3. **三个函数的"语义不一致"**：
   - `get_model_context_length` 认为"用户覆盖值 = 真实值"
   - `_check_compression_model_feasibility` 认为"aux_context = 模型检测值"
   - 但实际上 `aux_context` 可能来自配置覆盖，不是模型检测

### 修复

在 auto-lower 前加 guard：配置覆盖值不应触发 auto-lower。

```python
user_override = getattr(agent, '_aux_compression_context_length_config', None)
if (
    aux_context < threshold
    and (user_override is None or user_override != aux_context)
):
    # 只有真实模型检测值小于阈值时才 auto-lower
    agent.context_compressor.threshold_tokens = aux_context
```

---

## Bug 3：`_summarize_tool_result` 对 Dict 类型参数 Crash

### 现象

当 write_file 工具调用的 `content` 参数是 JSON 对象（而非纯文本）时，压缩系统全线崩溃：

```
AttributeError: 'dict' object has no attribute 'count'
→ _summarize_tool_result 失败
→ _prune_old_tool_results 失败  
→ compress() 失败
→ 上下文窗口溢出
```

### 根因

`_summarize_tool_result` 的类型假设：

```python
# 原代码假设 content 一定是 str
written_lines = args.get("content", "").count("\n") + 1
```

但模型输出的 tool call 参数可以是任意 JSON 类型。当 content 为 `{"key": "value"}` 时：
- `args.get("content", "")` 返回 dict（非空 → truthy）
- `.count("\n")` 在 dict 上调用 → `AttributeError`

同类问题还存在于 `execute_code` 和 `vision_analyze` 的 summarizer 分支——至少三个工具类型受影响。

### 修复

添加 `_safe_str()` 辅助函数，对非字符串类型做安全强制转换：

```python
def _safe_str(val, default=""):
    if isinstance(val, str):
        return val
    if val is None:
        return default
    return str(val)
```

---

## 系统性问题：为什么这三个 Bug 会同时存在

回头看，这三个 bug 共享一个根本原因：

**压缩系统依赖隐式的"值安全"假设，而不是显式类型约束。**

| Bug | 假设 | 实际 | 结果 |
|-----|------|------|------|
| Marker 传播 | `copy()` 不会传播内部状态 | 浅拷贝复制了 `_db_persisted` | 数据丢失 |
| Auto-lower | `aux_context` 来自模型检测 | 可能来自配置覆盖 | 性能退化 |
| Dict crash | `args.get("content")` 是 str | 可能是 dict/list | 运行时崩溃 |

在 Python 中，这三个假设都没有编译器或类型检查器来保护。它们只在运行时暴露，而且需要特定的用户配置或模型行为才能触发。

---

## 贡献影响

| Bug | 状态 | Commit 链接 |
|-----|------|-----------|
| Marker 传播 | ✅ **Merged to main**（2 commits） | `3e204bd` + `5eaccf5` |
| Auto-lower | PR 已提交 | [#58435](https://github.com/NousResearch/hermes-agent/pull/58435) |
| Dict crash | PR 已提交 | [#58442](https://github.com/NousResearch/hermes-agent/pull/58442) |

**最关键的是**：Top Contributor kshitijk4poor 在我们的 marker 传播修复之上构建了 follow-up commit——这是一个明确的质量认可信号。

---

## 学到的教训

1. **跨层调用链是 Bug 温床**。当值穿过 3 个函数后，原始含义可能已经丢失了
2. **"用户最了解"和"自动检测"需要明确区分**——不能把配置覆盖值当检测值用
3. **类型假设在 Python 中必须主动验证**——不能假设工具调用的参数类型
4. **内部状态（如 `_db_persisted`）应该有生命周期管理**——不应该通过拷贝传播

---

*本文基于我在 Hermes Agent 的实际贡献。所有分析都可以在 GitHub 上验证：[nankingjing 的 commits](https://github.com/NousResearch/hermes-agent/commits?author=nankingjing)*
