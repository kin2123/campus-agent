"""消息内容归一化。

## 为什么需要这个模块

实测（langchain-core 1.6.6 + langgraph 1.2.12）：**工具节点返回的 `ToolMessage.content`
不是字符串，而是内容块列表**：

```python
ToolMessage(content=[{'type': 'text', 'text': '工具返回的正文...'}])
```

直接 `str(content)` 会得到 Python repr —— 前端就会把
`[{'type': 'text', 'text': '...'}]` 原样显示给用户。这个 bug 在 HTTP 层的自检里
**查不出来**（自检只看 token 数量、关键词是否命中，repr 里同样含有关键词），
只有真的把界面渲染出来看才会发现。

注意 `AIMessage(content="...")` 直接构造时 content 仍是 `str`，
**列表是流经图之后才出现的**，所以"构造一个消息看看类型"这种验证方式会漏掉它。
"""
from __future__ import annotations

import json
from typing import Any


def content_to_text(content: Any) -> str:
    """把消息 content 归一化成纯文本。

    兼容四种形态：
    - `str`：直接用
    - `list[str]`：拼接
    - `list[dict]`：取每个块的 `text` 字段（LangChain 1.x 内容块格式）
    - 其他：退化为 `str()`
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                # {"type": "text", "text": "...", "id": "..."}
                if "text" in block and isinstance(block["text"], str):
                    parts.append(block["text"])
                elif block.get("type") == "image_url":
                    parts.append("[图片]")
                else:
                    parts.append(json.dumps(block, ensure_ascii=False))
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content)
