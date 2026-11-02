"""脚本假模型：不依赖任何 API Key，按规则产出 tool_calls。

## 它到底能验证什么、不能验证什么

**能验证（链路层）**：
- MCP 连接是否真的建立、工具 schema 能否被模型侧看到
- ReAct 循环能否跑通（模型 → 工具 → 模型 → 回答）
- SSE 事件流是否按预期推送（model 节点 / tools 节点）
- HumanInTheLoopMiddleware 的中断与恢复是否正常
- 身份透传是否生效（工具带的是当前用户的票据）
- 拒绝审批后，写操作是否真的没有落库

**不能验证（推理层）**：
- 模型会不会**选错工具**（这里是规则驱动，不是理解）
- 模型在越界任务下会不会**幻觉**（这里是写死的拒绝话术）

所以接上真实模型后，必须重新跑 `scripts/eval_agent.py` 验证工具选择准确率。

## 实现要点

- 可变状态用 `PrivateAttr`，可序列化字段用 `Field`（pydantic v2 要求）
- `bind_tools` 必须返回 self，并**记录**工具名（排查「模型看不到工具」必看）
- 覆盖 `_astream` 才能让 SSE 真正逐字推送；只实现 `_generate` 会整段吐出
"""
from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Iterator
from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field, PrivateAttr

from .text import content_to_text

COURSE_CODE_RE = re.compile(r"\b([A-Za-z]{2}\s?\d{3})\b")

# ---------------------------------------------------------------------------- 意图规则
# 顺序即优先级：越界判断必须排在最前，否则「帮我改一下成绩」会被
# 「帮我」命中写成选课意图。

BOUNDARY_RULES: list[tuple[tuple[str, ...], str]] = [
    (
        ("改成绩", "修改成绩", "把成绩改", "改一下成绩", "改成 90", "录成绩", "提分"),
        "我没有修改成绩的权限 —— 成绩是学籍凭证，任何改动都必须走教务人工审核流程，"
        "Agent 工具集里刻意没有开放这个能力。如果你认为成绩有误，"
        "可在成绩公布后 10 个工作日内向开课院系教学秘书提交《成绩复核申请表》，"
        "复核范围限登分错误、漏批、合分错误。",
    ),
    (
        ("重置密码", "改密码", "修改密码", "找回密码"),
        "我不能操作账号安全相关的功能，工具集里没有开放改密能力。"
        "如需重置密码请携带学生证到信息中心 9 号窗办理。",
    ),
    (
        ("免修", "缓考申请", "缓考怎么办", "提交缓考", "办缓考"),
        "缓考/免修属于需要上传证明材料的审批流程，我没有权限代办，"
        "工具集里也没有开放。你需要：考前提交《缓考申请表》并附二级甲等以上医院证明，"
        "经院系审核、教务处批准后生效。考前未办手续且缺考的按 0 分计。",
    ),
    (
        ("替我考试", "代考", "帮我作弊"),
        "这个我不能做，也不会协助。",
    ),
]

DROP_RULES = ("退课", "退了", "退掉", "不想上", "取消选课", "不要这门", "删掉这门")
ENROLL_RULES = ("帮我选", "我要选", "想选", "选上", "加课", "选课", "报了", "加上")
GRADE_RULES = ("成绩", "绩点", "考了多少", "分数", "挂科", "及不及格", "过了吗", "GPA", "gpa")
SCHEDULE_RULES = ("课表", "我选了什么", "我选上", "我的课", "冲突", "周几有课", "排课")
LIST_RULES = ("有哪些课", "什么课", "课程列表", "余量", "名额", "还有位置", "可以选什么", "开课")
DETAIL_RULES = ("讲什么", "是什么课", "课程详情", "介绍一下", "教什么", "内容是什么")
KNOWLEDGE_RULES = (
    "学分", "规定", "规则", "怎么", "如何", "为什么", "多少", "限制", "要求",
    "流程", "政策", "标准", "条件", "上限", "能不能", "可以吗", "需要",
)


def _extract_course_code(text: str) -> str | None:
    m = COURSE_CODE_RE.search(text)
    return m.group(1).replace(" ", "").upper() if m else None


class ScriptedChatModel(BaseChatModel):
    """按规则产出 tool_calls 的假模型。"""

    # 可序列化字段
    script_label: str = Field(default="rule-based-scripted", description="标识，便于日志区分")
    call_count: int = Field(default=0, description="已产生的模型回复数，用于排查循环")

    # 可变内部状态必须用 PrivateAttr（pydantic v2）
    _visible_tools: list[str] = PrivateAttr(default_factory=list)
    _alias: dict[str, str] = PrivateAttr(default_factory=dict)
    _pending: list[AIMessage] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    # ---------------------------------------------------------------- 工具绑定

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        """记录模型可见的工具名，并建立「裸名 -> 实际名」映射。

        实测坑一：`create_agent` 不在构造时绑定工具，绑定发生在每次调模型前。
        所以构造完 agent 立刻查「模型可见哪些工具」会得到空列表 ——
        必须在这里（或 ainvoke 之后）看才是真实的。

        实测坑二：`MultiServerMCPClient(tool_name_prefix=True)` 会把工具名变成
        `campus_enroll_course`（MCP 规范要求聚合多服务时加前缀）。
        所以内部用裸名（`enroll_course`）写规则，调用时再翻译成实际名 ——
        否则会误判成「我当前没有这个工具」。
        """
        names: list[str] = []
        for tool in tools or []:
            if isinstance(tool, dict):
                names.append(tool.get("name") or tool.get("function", {}).get("name", ""))
            else:
                names.append(getattr(tool, "name", getattr(tool, "__name__", str(tool))))
        names = [n for n in names if n]
        if names:
            self._visible_tools = names
            alias: dict[str, str] = {}
            for actual in names:
                alias[actual] = actual
                # 剥掉 server 前缀：campus_enroll_course -> enroll_course
                for known in (
                    "list_courses", "get_course_detail", "get_my_schedule",
                    "get_my_grades", "search_knowledge", "enroll_course", "drop_course",
                ):
                    if actual.endswith(f"_{known}"):
                        alias[known] = actual
            self._alias = alias
        return self

    @property
    def visible_tools(self) -> list[str]:
        return list(self._visible_tools)

    # ---------------------------------------------------------------- 决策

    def _last_human(self, messages: list[BaseMessage]) -> str:
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                return content_to_text(msg.content)
        return ""

    def _tool_messages(self, messages: list[BaseMessage]) -> list[ToolMessage]:
        """只取**最后一条用户消息之后**的 ToolMessage。

        这里踩过一个坑：checkpointer 会保留整个 thread 的历史，
        所以同一 thread_id 的第二轮对话里，messages 里还带着上一轮的 ToolMessage。
        如果不过滤，模型会误以为"这轮已经有工具结果了"，直接收尾回答，
        于是**第二轮之后再也不调工具** —— 表现为「ReAct 循环只在第一轮生效」。
        """
        last_human = -1
        for i in range(len(messages) - 1, -1, -1):
            if isinstance(messages[i], HumanMessage):
                last_human = i
                break
        return [
            m for m in messages[last_human + 1 :] if isinstance(m, ToolMessage)
        ]

    def _decide(self, messages: list[BaseMessage]) -> AIMessage:
        """决定这一轮是调工具还是直接回答。"""
        tool_msgs = self._tool_messages(messages)
        human = self._last_human(messages)

        # 已经有工具结果 -> 收尾回答，避免无限循环
        if tool_msgs:
            return AIMessage(content=self._summarize(human, tool_msgs))

        available = set(self._visible_tools) or {
            "list_courses", "get_course_detail", "get_my_schedule",
            "get_my_grades", "search_knowledge", "enroll_course", "drop_course",
        }
        # 内部一律用裸名判断，调用时翻译成 MCP 实际暴露的名字
        alias = self._alias or {}

        def resolve(bare: str) -> str | None:
            if bare in available:
                return bare
            return alias.get(bare)

        # ---- 1. 越界：工具集里没有这个能力，明确拒绝，绝不硬凑工具 ----
        for keywords, reply in BOUNDARY_RULES:
            if any(k in human for k in keywords):
                return AIMessage(content=reply)

        code = _extract_course_code(human)
        low = human.lower()

        def call(bare: str, args: dict) -> AIMessage:
            actual = resolve(bare)
            if actual is None:
                # 这是诚实的失败：工具集里确实没有这个能力。
                # 真实模型在这里最容易犯的错是「硬凑一个不相干的工具」，
                # 假模型不会，但这行代码本身也是给真模型看的示范。
                return AIMessage(
                    content=f"我当前没有 `{bare}` 这个工具，无法完成这个操作。"
                )
            return AIMessage(
                content="",
                tool_calls=[
                    {"name": actual, "args": args,
                     "id": f"call_{self.call_count + 1}", "type": "tool_call"}
                ],
            )

        # ---- 2. 写操作优先于读操作 ----
        # 顺序很重要：「帮我退了 CS208」不该被「选课」规则抢走
        if any(k in human for k in DROP_RULES):
            if code:
                return call("drop_course", {"course_code": code})
            return AIMessage(
                content="你想退哪门课？请告诉我课程代码（例如 CS208），"
                "我可以先查一下你的课表确认。"
            )

        if any(k in human for k in ENROLL_RULES):
            if code:
                return call("enroll_course", {"course_code": code})
            return AIMessage(
                content="你想选哪门课？告诉我课程代码（例如 CS204）我就能帮你选。"
                "如果你想先看看有哪些课，也可以直接问我。"
            )

        # ---- 3. 读操作 ----
        if any(k in human for k in GRADE_RULES):
            return call("get_my_grades", {})

        if any(k in human for k in SCHEDULE_RULES):
            return call("get_my_schedule", {})

        # 带课程代码 + 详情类问法 -> 查详情
        if code and any(k in human for k in DETAIL_RULES):
            return call("get_course_detail", {"course_code": code})

        if any(k in human for k in LIST_RULES) or (code and "余量" in human):
            args: dict[str, Any] = {}
            if any(k in human for k in ("还有", "余量", "名额", "位置", "能选")):
                args["only_available"] = True
            if "人工智能" in human:
                args["category"] = "专业选修"
                args["keyword"] = ""
            return call("list_courses", args)

        if any(k in human for k in KNOWLEDGE_RULES):
            return call("search_knowledge", {"query": human})

        # ---- 4. 兜底：不猜，直接说明能力范围 ----
        return AIMessage(
            content=(
                "我可以帮你做这些事：\n"
                "· 查课程列表、课程详情、剩余名额（例如「还有哪些课能选」）\n"
                "· 查你的课表和已出成绩、绩点（例如「我的课表」「我绩点多少」）\n"
                "· 回答学校规章制度（例如「一学期最多选多少学分」「缓考怎么申请」）\n"
                "· 帮你选课 / 退课（执行前会请你确认）\n\n"
                "把你想做的事说得具体一点，我就能直接办了。"
            )
        )

    # ---------------------------------------------------------------- 收尾回答

    def _summarize(self, human: str, tool_msgs: list[ToolMessage]) -> str:
        """把工具结果组织成自然语言回答。

        注意：这里**直接引用工具的返回原文**，不做二次发挥 ——
        假模型的定位是演示链路，不是假装有推理能力。
        """
        names = [m.name for m in tool_msgs]
        parts: list[str] = []

        for msg in tool_msgs:
            content = content_to_text(msg.content).strip()
            name = msg.name
            if name == "search_knowledge":
                parts.append("根据学校规定：\n" + content)
            elif name == "get_my_grades":
                parts.append("你的成绩情况：\n" + content)
            elif name == "get_my_schedule":
                parts.append("你的课表：\n" + content)
            elif name == "list_courses":
                parts.append("符合条件的课程：\n" + content)
            elif name == "get_course_detail":
                parts.append("课程详情：\n" + content)
            elif name in ("enroll_course", "drop_course"):
                parts.append(content)
            else:
                parts.append(content)

        body = "\n\n".join(parts)
        if any(n in ("enroll_course", "drop_course") for n in names):
            return body
        return body

    # ---------------------------------------------------------------- 生成

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        message = self._decide(messages)
        self.call_count += 1
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages, stop=stop, run_manager=None, **kwargs)

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        message = self._decide(messages)
        self.call_count += 1
        yield from self._chunkify(message, run_manager)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """逐字推送，让 SSE 的流式效果是真实的而不是整段到达。"""
        message = self._decide(messages)
        self.call_count += 1
        for chunk in self._chunkify(message, None):
            if run_manager is not None:
                await run_manager.on_llm_new_token(chunk.text, chunk=chunk)
            yield chunk

    @staticmethod
    def _chunkify(
        message: AIMessage,
        run_manager: CallbackManagerForLLMRun | None,
    ) -> Iterator[ChatGenerationChunk]:
        # tool_calls 必须整块给出，不能切
        if getattr(message, "tool_calls", None):
            chunk = ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": tc["name"],
                            "args": json.dumps(tc["args"], ensure_ascii=False),
                            "id": tc["id"],
                            "index": i,
                            "type": "tool_call_chunk",
                        }
                        for i, tc in enumerate(message.tool_calls)
                    ],
                )
            )
            if run_manager is not None:
                run_manager.on_llm_new_token(chunk.text, chunk=chunk)
            yield chunk
            return

        # content 流经图之后可能是内容块列表，必须归一化
        text = content_to_text(message.content)
        step = 6  # 每 6 个字符一个 chunk，模拟真实流式的节奏
        for i in range(0, len(text), step):
            piece = text[i : i + step]
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=piece))
            if run_manager is not None:
                run_manager.on_llm_new_token(piece, chunk=chunk)
            yield chunk
