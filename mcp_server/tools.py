"""MCP 工具集。

## 写工具与读工具的边界

| 工具 | 类型 | 是否需人工审批 |
|---|---|---|
| list_courses / get_course_detail / get_my_schedule / get_my_grades / search_knowledge | 读 | 否 |
| enroll_course / drop_course | 写（有副作用） | **是** |

审批登记在 Agent 层（HumanInTheLoopMiddleware 的 `interrupt_on`），
这里只负责实现。**只登记写工具**，读工具不登记 → 误拦率为 0。

## 刻意没有暴露成工具的能力（boundary）

以下能力业务系统有或未来会有，但**有意不做成工具**，因为让模型自动执行风险过高：

- 修改/录入成绩 —— 成绩是学籍凭证，改动必须走教务人工审核
- 重置密码、修改个人信息 —— 涉及账号安全
- 免修/缓修/缓考申请 —— 需上传证明材料，属于带附件的审批流
- 教师端排课、容量调整 —— 管理权限，不应由学生端 Agent 触发

这几个正好是评测 Agent 安全性时的天然 boundary 用例：
**工具集里根本没有这个能力时，模型会不会硬凑一个不相干的工具、会不会幻觉「已办理」。**

## 每个 docstring 都要写清「何时用、何时不用」

docstring 是模型选工具的唯一依据。写「查询课程」这种笼统描述会导致
「我想退课」时模型去调 `list_courses`。所以要显式写出反面：
「只查规则和制度，不要用这个工具查课程是否还有名额」。
"""
from __future__ import annotations

from mcp.server.fastmcp import Context

from .business_client import ToolError, call_business


def _fail(exc: ToolError) -> str:
    return f"操作失败（{exc.code}）：{exc.message}"


def _fmt_course(row: dict) -> str:
    prereq = row.get("prerequisite_codes") or "无"
    return (
        f"· {row['code']}《{row['name']}》 {row['teacher_name']} | "
        f"{row['credits']} 学分 | {row['category']} | "
        f"周{row['weekday']} 第{row['start_slot']}-{row['end_slot']}节 {row['location']} | "
        f"余量 {row['remaining']}/{row['capacity']} | 考核 {row['exam_type']} | "
        f"先修 {prereq}"
    )


# --------------------------------------------------------------------------- 读工具


async def list_courses(
    ctx: Context,
    keyword: str = "",
    category: str = "",
    only_available: bool = False,
) -> str:
    """查询可选课程列表，可按课程名/代码/教师搜索、按类别筛选、只看还有名额的课。

    何时用：学生想知道「有什么课可以选」「XX 老师开什么课」「还有哪些课没满」
    「人工智能方向有哪些课」「CS202 有几个名额」。

    何时不用：不要用这个工具查培养方案、选课规则、考试规定等制度性问题，
    那些要用 search_knowledge。也不要用它查「我已经选了什么课」，那要用 get_my_schedule。

    Args:
        keyword: 课程名/课程代码/教师名的模糊匹配关键词，留空表示不限。
        category: 课程类别精确匹配，可选值：专业必修、专业选修、通识必修、通识选修、学科基础。留空表示不限。
        only_available: 为 True 时只返回还有剩余名额的课程。学生问「还有什么课能选」时应该传 True。
    """
    try:
        rows = await call_business(
            ctx,
            "GET",
            "/api/courses",
            params={
                "keyword": keyword or None,
                "category": category or None,
                "only_available": only_available,
            },
        )
    except ToolError as exc:
        return _fail(exc)

    if not rows:
        cond = []
        if keyword:
            cond.append(f"关键词「{keyword}」")
        if category:
            cond.append(f"类别「{category}」")
        if only_available:
            cond.append("仅有余量")
        desc = "、".join(cond) or "当前条件"
        return f"没有找到符合条件的课程（{desc}）。可以放宽筛选条件再试。"

    lines = [f"共 {len(rows)} 门课程："]
    lines.extend(_fmt_course(r) for r in rows)
    return "\n".join(lines)


async def get_course_detail(ctx: Context, course_code: str) -> str:
    """按课程代码查询某门课的详细信息，含课程简介、先修要求、考核方式、上课时间地点。

    何时用：学生问「CS204 是什么课」「操作系统讲什么」「这门课有什么先修要求」
    「CS204 什么时候上」。

    何时不用：查课程列表用 list_courses；查自己已选的课用 get_my_schedule。

    Args:
        course_code: 课程代码，如 CS204。必须是完整代码，不是课程名。
    """
    try:
        row = await call_business(ctx, "GET", f"/api/courses/by-code/{course_code}")
    except ToolError as exc:
        return _fail(exc)

    return "\n".join(
        [
            f"{row['code']}《{row['name']}》",
            f"教师：{row['teacher_name']}",
            f"学分：{row['credits']}　类别：{row['category']}　学期：{row['semester']}",
            f"时间地点：周{row['weekday']} 第{row['start_slot']}-{row['end_slot']}节，{row['location']}",
            f"容量：{row['enrolled_count']}/{row['capacity']}（剩余 {row['remaining']}）",
            f"考核方式：{row['exam_type']}",
            f"先修课程：{row['prerequisite_codes'] or '无'}",
            f"课程简介：{row['description'] or '暂无'}",
        ]
    )


async def get_my_schedule(ctx: Context) -> str:
    """查询「当前登录学生」本人的课表，返回本学期已选的全部课程及上课时间地点。

    何时用：学生问「我的课表」「我这学期选了什么课」「我周三有什么课」
    「我选上课了吗」「这门课和我其他课冲突吗」。

    何时不用：查成绩用 get_my_grades。这个工具只能查本人的，查不了别人的。
    """
    try:
        rows = await call_business(ctx, "GET", "/api/me/schedule")
    except ToolError as exc:
        return _fail(exc)

    if not rows:
        return "你当前还没有选任何课程，课表是空的。可以让我帮你看看有哪些课可以选。"

    total_credits = sum(float(r["credits"]) for r in rows)
    lines = [f"你已选 {len(rows)} 门课，共 {total_credits:g} 学分："]
    for r in sorted(rows, key=lambda x: (x["weekday"], x["start_slot"])):
        lines.append(
            f"· 周{r['weekday']} 第{r['start_slot']}-{r['end_slot']}节 | "
            f"{r['code']}《{r['name']}》 {r['teacher_name']} | "
            f"{r['credits']} 学分 | {r['location']}"
        )
    return "\n".join(lines)


async def get_my_grades(ctx: Context) -> str:
    """查询「当前登录学生」本人的已出成绩课程，含单科分数、学分与平均绩点。

    何时用：学生问「我的成绩」「我考了多少分」「我的绩点是多少」
    「我 CS201 过了吗」「我有没有挂科」。

    何时不用：查课表用 get_my_schedule。这个工具只能查本人的成绩，查不了别人的。
    未出成绩的课程不会出现在结果里，如果学生问的课没出现，要说明「成绩还没录入」。
    """
    try:
        data = await call_business(ctx, "GET", "/api/me/grades")
    except ToolError as exc:
        return _fail(exc)

    items = data.get("items", [])
    if not items:
        return "你目前还没有已录入的成绩。本学期课程如果还没出分，请稍后再查。"

    lines = [
        f"已出成绩 {data['course_count']} 门，总学分 {data['total_credit']}，"
        f"加权平均分 {data['average']}，平均绩点 {data['gpa']}："
    ]
    for it in items:
        lines.append(
            f"· {it['course_code']}《{it['course_name']}》 "
            f"{it['credits']} 学分 {it['score']} 分（绩点 {it['grade_point']}）"
        )
    return "\n".join(lines)


async def search_knowledge(ctx: Context, query: str) -> str:
    """检索学校规章制度与培养方案知识库，回答「规定是什么」类的制度性问题。

    何时用：所有制度、规则、流程类问题，例如「一学期最多能选多少学分」
    「退课有什么限制」「缓考怎么申请」「毕业需要多少学分」「奖学金怎么评」
    「作弊会怎么处理」「实验室设备能借多久」「校园网每月多少流量」。
    也用于回答「为什么选课失败了」这类需要解释规则的问题。

    何时不用：**不要用这个工具查学生的个人数据**（自己的课表、成绩、选课记录），
    那些要用 get_my_schedule / get_my_grades；也不要查课程列表，用 list_courses。

    Args:
        query: 用自然语言描述要查询的问题，不要只给关键词。例如问「退课有什么限制」比只传「退课」召回效果好。
    """
    try:
        data = await call_business(
            ctx, "POST", "/api/knowledge/search",
            params={"q": query, "top_k": 4, "x_source": "AI"},
        )
    except ToolError as exc:
        return _fail(exc)

    hits = data.get("hits", [])
    if not hits:
        return (
            f"知识库里没有检索到与「{query}」相关的规定。"
            "建议向教务处或辅导员确认，不要凭猜测作答。"
        )

    lines = [f"围绕「{query}」检索到 {len(hits)} 条相关规定："]
    for i, h in enumerate(hits, 1):
        lines.append(f"\n【依据 {i}】{h['title']}（来源：{h['source_file']}）")
        lines.append(h["content"])
    lines.append("\n请只依据以上材料回答，并在回答中说明依据来自哪份文件。")
    return "\n".join(lines)


# --------------------------------------------------------------------------- 写工具（需人工审批）


async def enroll_course(ctx: Context, course_code: str) -> str:
    """为「当前登录学生」本人选课。这是有副作用的写操作，执行前会请求本人确认。

    何时用：学生明确表达要选某门课，例如「帮我选 CS204」「我要选机器学习」
    「把深度学习加进我的课表」。只有在学生提供了具体课程代码或明确课程名时才调用。

    何时不用：学生只是在**了解**课程信息（「CS204 讲什么」「有什么课可以选」）时，
    绝对不要调用这个工具 —— 那属于查询，用 list_courses / get_course_detail。
    学生问「我能选吗」时也应先用查询工具确认余量和先修要求，而不是直接选。

    调用后如果被拒绝，结果里会带有明确的 reason code，请如实把原因告诉学生，
    不要重复调用同一个操作。

    Args:
        course_code: 要选的课程代码，如 CS204。必须是完整代码。
    """
    try:
        result = await call_business(
            ctx, "POST", "/api/enrollments",
            json_body={"course_code": course_code.strip().upper()},
            write=True,
        )
    except ToolError as exc:
        return (
            f"选课未成功（{exc.code}）：{exc.message}\n"
            "请把这个确切原因转告学生，不要自行重试或改用其他课程。"
        )
    return f"选课成功：{result.get('message', '')}"


async def drop_course(ctx: Context, course_code: str) -> str:
    """为「当前登录学生」本人退课。这是有副作用的写操作，执行前会请求本人确认。

    何时用：学生明确要求退掉某门已选课程，例如「帮我退了编译原理」
    「CS208 我不想上了，退掉」。只有在学生明确表达了退课意图时才调用。

    何时不用：学生只是在问课程信息或规则（「退课有什么限制」）时，
    绝对不要调用这个工具 —— 那是制度问题，用 search_knowledge。

    注意：已出成绩的课程无法退课。调用后如果被拒绝，请如实转告原因，不要重试。

    Args:
        course_code: 要退的课程代码，如 CS208。必须是完整代码。
    """
    try:
        result = await call_business(
            ctx, "DELETE", f"/api/enrollments/{course_code.strip().upper()}", write=True
        )
    except ToolError as exc:
        return (
            f"退课未成功（{exc.code}）：{exc.message}\n"
            "请把这个确切原因转告学生，不要自行重试。"
        )
    return f"退课成功：{result.get('message', '')}"


# 读工具清单（不登记审批）
READ_TOOLS = [
    list_courses,
    get_course_detail,
    get_my_schedule,
    get_my_grades,
    search_knowledge,
]

WRITE_TOOLS = [
    enroll_course,
    drop_course,
]

ALL_TOOLS = READ_TOOLS + WRITE_TOOLS

# 与 Agent 层 HumanInTheLoopMiddleware 的 interrupt_on 对齐。
# 放在这里而不是 Agent 层，是为了「加一个写工具就自动进入审批」，
# 避免出现「新加了写工具但忘了登记审批」这种致命疏漏。
WRITE_TOOL_NAMES = [fn.__name__ for fn in WRITE_TOOLS]
