"""模型工厂：在「假模型」和「真实模型」之间切换。

## 为什么要有假模型

**把「链路是否贯通」和「模型是否聪明」解耦。**

没 API Key 的时候，如果只能等拿 Key 才能测试，那 MCP 连接对不对、
工具绑定成功没有、ReAct 循环能不能跑、SSE 事件流对不对、审批中断能不能恢复
—— 这些全都无法验证，只能靠祈祷。

脚本假模型按预设产出 `tool_calls`，不依赖任何网络和推理能力，
于是上面每一项都能被独立验证。真模型接上后，**必须重新验证工具选择准确率**
（假模型不具备推理能力，测不出"模型会不会选错工具"）。

## 切换方式

改 `backend/.env` 里的 `LLM_PROVIDER`：
    fake                  假模型（默认，无需 Key）
    deepseek              需要 LLM_API_KEY
    zhipu                 需要 LLM_API_KEY
    openai_compatible     需要 LLM_API_KEY + LLM_BASE_URL + LLM_MODEL
"""
from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from ..config import settings
from .scripted_model import ScriptedChatModel

# 各家的 OpenAI 兼容端点。base_url 是否含 /v1 各家不同，
# 写错的报错是 404 而不是 401，很容易误判成「Key 不对」。
PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
    },
}


def build_model() -> BaseChatModel:
    provider = (settings.llm_provider or "fake").strip().lower()

    if provider == "fake":
        return ScriptedChatModel()

    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "接入真实模型需要 langchain-openai，请先安装："
            "pip install langchain-openai"
        ) from exc

    defaults = PROVIDER_DEFAULTS.get(provider, {})
    base_url = settings.llm_base_url or defaults.get("base_url", "")
    model = settings.llm_model or defaults.get("model", "")

    if not settings.llm_api_key:
        raise RuntimeError(
            f"LLM_PROVIDER={provider} 需要 LLM_API_KEY，但 .env 里是空的。"
            "填好 Key 或改回 LLM_PROVIDER=fake 用假模型跑通链路。"
        )
    if not base_url or not model:
        raise RuntimeError(
            f"LLM_PROVIDER={provider} 缺少 base_url 或 model，"
            "请在 .env 里设置 LLM_BASE_URL 和 LLM_MODEL。"
        )

    return ChatOpenAI(
        model=model,
        api_key=settings.llm_api_key,
        base_url=base_url,
        temperature=settings.llm_temperature,
        timeout=60,
        max_retries=2,
    )


def describe_provider() -> dict[str, Any]:
    """给前端/自检脚本展示当前用的是哪个模型。"""
    provider = (settings.llm_provider or "fake").strip().lower()
    if provider == "fake":
        return {
            "provider": "fake",
            "is_fake": True,
            "note": "当前使用内置脚本假模型：链路真实、推理是规则模拟的。"
                    "配好 LLM_API_KEY 并改 LLM_PROVIDER 即可切换真实模型。",
        }
    defaults = PROVIDER_DEFAULTS.get(provider, {})
    return {
        "provider": provider,
        "is_fake": False,
        "model": settings.llm_model or defaults.get("model", ""),
        "base_url": settings.llm_base_url or defaults.get("base_url", ""),
        "note": "已接入真实模型。",
    }
