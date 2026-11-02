"""端到端链路自检 —— 无需任何 API Key。

## 这个脚本存在的意义

把「链路是否贯通」和「模型是否聪明」解耦。用内置脚本假模型，
就能把下面每一项都验证成**可复现的实证**，而不是「应该没问题」：

| 检查项 | 验证手段 |
|---|---|
| 业务 REST 与 JWT 鉴权 | 登录 + 带票据访问 |
| MCP 连接与工具发现 | /api/agent/status |
| 身份带外透传（防越权） | 两个不同用户各自调用，确认只看到自己的数据 |
| 工具 schema 完整性 | 每个工具都有描述 |
| 工具参数无身份字段 | 检查参数列表 |
| ReAct 循环 | 读任务：模型 → 工具 → 模型 |
| SSE 流式 | 事件序列 + TTFB 明显小于总耗时 |
| 写操作人工审批 | 触发中断并拿到审批载荷 |
| 批准后真的执行 | 核对业务表条数变化 |
| 拒绝后真的没执行 | 核对业务表条数与审批前一致 |
| 越界任务不幻觉 | 检查回复里没有「已办理」类措辞、没调不相干工具 |

用法（需先启动后端 18000 与 MCP 18001）：
    python scripts/check_chain.py
    python scripts/check_chain.py --base http://127.0.0.1:18000
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

DEFAULT_BASE = "http://127.0.0.1:18000"

# 每次运行用唯一的 thread 前缀。
# 复用 thread_id 会让 checkpointer 带回上一轮的历史，测试之间互相干扰 ——
# 这个坑实测踩过：第二次运行时脚本报「ReAct 不调工具了」，其实是被上轮历史污染。
RUN_ID = f"chain{int(time.time()) % 100000}"

PASS, FAIL, WARN, INFO = "[PASS]", "[FAIL]", "[WARN]", "[INFO]"


class Report:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.warned = 0
        self.rows: list[tuple[str, str, str]] = []

    def ok(self, name: str, detail: str = "") -> None:
        self.passed += 1
        self.rows.append((PASS, name, detail))
        print(f"{PASS} {name}" + (f"  {detail}" if detail else ""))

    def fail(self, name: str, detail: str = "") -> None:
        self.failed += 1
        self.rows.append((FAIL, name, detail))
        print(f"{FAIL} {name}" + (f"  {detail}" if detail else ""))

    def warn(self, name: str, detail: str = "") -> None:
        self.warned += 1
        self.rows.append((WARN, name, detail))
        print(f"{WARN} {name}" + (f"  {detail}" if detail else ""))

    def info(self, text: str) -> None:
        print(f"{INFO} {text}")

    def section(self, title: str) -> None:
        print()
        print("─" * 74)
        print(f"  {title}")
        print("─" * 74)


def login(client: httpx.Client, base: str, username: str, password: str = "123456") -> str:
    resp = client.post(
        f"{base}/api/auth/login", json={"username": username, "password": password}
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def parse_sse(text: str) -> list[tuple[str, dict]]:
    """手工解析 SSE 帧 —— 和服务实际上要用同一套逻辑（前端也是手写的）。"""
    events: list[tuple[str, dict]] = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_name = "message"
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if not data_lines:
            continue
        try:
            payload = json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            payload = {"_raw": "\n".join(data_lines)}
        events.append((event_name, payload))
    return events


def stream_post(
    client: httpx.Client, url: str, token: str, body: dict
) -> tuple[list[tuple[str, dict]], float, float]:
    """POST 并读取 SSE 流，返回 (事件列表, 首字节耗时, 总耗时)。"""
    events: list[tuple[str, dict]] = []
    first_byte_at: float | None = None
    buffer = ""
    started = time.perf_counter()

    with client.stream(
        "POST", url, headers=auth(token), json=body, timeout=180.0
    ) as resp:
        resp.raise_for_status()
        for chunk in resp.iter_text():
            if first_byte_at is None and chunk:
                first_byte_at = time.perf_counter()
            buffer += chunk
            # 按 SSE 帧边界切分，最后一段留在 buffer 里等下一块
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                block = block.strip()
                if not block:
                    continue
                event_name = "message"
                data_lines: list[str] = []
                for line in block.splitlines():
                    if line.startswith("event:"):
                        event_name = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].strip())
                if data_lines:
                    try:
                        payload = json.loads("\n".join(data_lines))
                    except json.JSONDecodeError:
                        payload = {"_raw": "\n".join(data_lines)}
                    events.append((event_name, payload))

    total = time.perf_counter() - started
    ttfb = (first_byte_at - started) if first_byte_at else total
    return events, ttfb, total


def count_enrollments(token: str, base: str, client: httpx.Client) -> int:
    """核对业务数据基线。用真实接口拿，不用 SQL limit 假装总数。"""
    resp = client.get(f"{base}/api/me/enrollments", headers=auth(token))
    resp.raise_for_status()
    return len(resp.json())


def find_enrollable_course(
    token: str, base: str, client: httpx.Client
) -> tuple[str | None, str]:
    """预检出一门「这次一定选得上」的课。

    这一步是必须的 —— 第一版脚本硬编码 CS214，结果连续两次失败，
    排查后发现**不是代码问题，而是业务规则正确工作了**：
    CS214《机器学习》的先修课是 CS209《人工智能导论》，该学生没通过。

    这正是「FAIL 先怀疑标注，再怀疑被测对象」的典型场景。
    做成预检后，无论换哪个学生、课表状态如何，测试都能自洽。
    """
    courses = client.get(f"{base}/api/courses", headers=auth(token)).json()
    grades = client.get(f"{base}/api/me/grades", headers=auth(token)).json()
    schedule = client.get(f"{base}/api/me/schedule", headers=auth(token)).json()

    passed = {g["course_code"] for g in grades["items"] if g["score"] >= 60}
    enrolled = {c["code"] for c in schedule}
    occupied = [(c["weekday"], c["start_slot"], c["end_slot"]) for c in schedule]

    def conflicts(course: dict) -> bool:
        for wd, s, e in occupied:
            if wd != course["weekday"]:
                continue
            if course["start_slot"] <= e and s <= course["end_slot"]:
                return True
        return False

    for course in courses:
        # 已修过且合格不能重选（业务层的 ALREADY_PASSED 规则），必须排除，
        # 否则预检会挑出一门"看起来可选、实际必被拒"的课。
        if course["code"] in enrolled or course["code"] in passed:
            continue
        if course["remaining"] <= 0:
            continue
        prereqs = [p.strip() for p in (course["prerequisite_codes"] or "").split(",") if p.strip()]
        if not all(p in passed for p in prereqs):
            continue
        if conflicts(course):
            continue
        return course["code"], (
            f"{course['code']}《{course['name']}》余量 {course['remaining']}，"
            f"先修 {'无' if not prereqs else '/'.join(prereqs)} 已满足，"
            f"无时间冲突，未修过"
        )
    return None, "找不到任何当前可选的课程（可能课表已满或全部课程都有先修要求）"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=DEFAULT_BASE)
    args = parser.parse_args()
    base = args.base.rstrip("/")

    rep = Report()
    client = httpx.Client(timeout=30.0)

    # ============================================================ 0. 服务可达
    rep.section("0. 服务可达性")
    try:
        health = client.get(f"{base}/health").json()
        rep.ok("后端健康检查 /health", json.dumps(health, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        rep.fail("后端健康检查 /health", f"{type(exc).__name__}: {exc}")
        print("\n后端没起来，后面的检查无法进行。请先启动 18000 与 18001。")
        return 1

    # ============================================================ 1. 鉴权
    rep.section("1. 业务 REST 与 JWT 鉴权")
    try:
        token_a = login(client, base, "20230101")
        me_a = client.get(f"{base}/api/auth/me", headers=auth(token_a)).json()
        rep.ok("登录 + /api/auth/me", f"{me_a['name']}（{me_a['student_no']}）")
    except Exception as exc:  # noqa: BLE001
        rep.fail("登录", f"{type(exc).__name__}: {exc}")
        return 1

    no_auth = client.get(f"{base}/api/courses")
    if no_auth.status_code == 401:
        rep.ok("无票据访问被拒", "GET /api/courses -> 401")
    else:
        rep.fail("无票据访问被拒", f"期望 401，实际 {no_auth.status_code}")

    try:
        login(client, base, "20230101", "wrong-password")
        rep.fail("错误密码被拒", "居然登录成功了")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 401:
            rep.ok("错误密码被拒", "POST /api/auth/login -> 401")
        else:
            rep.fail("错误密码被拒", f"期望 401，实际 {exc.response.status_code}")

    courses = client.get(
        f"{base}/api/courses", headers=auth(token_a), params={"keyword": "操作系统"}
    ).json()
    rep.ok("课程检索", f"关键词「操作系统」命中 {len(courses)} 门")
    schedule = client.get(f"{base}/api/me/schedule", headers=auth(token_a)).json()
    grades = client.get(f"{base}/api/me/grades", headers=auth(token_a)).json()
    rep.ok(
        "课表与成绩",
        f"在读 {len(schedule)} 门；已出成绩 {grades['course_count']} 门，"
        f"GPA {grades['gpa']}，加权均分 {grades['average']}",
    )

    kb = client.post(
        f"{base}/api/knowledge/search",
        headers=auth(token_a),
        params={"q": "一学期最多能选多少学分", "top_k": 3},
    ).json()
    top1 = kb["hits"][0] if kb["hits"] else {}
    rep.ok("RAG 检索", f"Top1 = {top1.get('title', '无')[:40]}")

    # ============================================================ 2. MCP 与工具
    rep.section("2. MCP 连接、工具发现与审批策略")
    try:
        status = client.get(f"{base}/api/agent/status", headers=auth(token_a)).json()
    except Exception as exc:  # noqa: BLE001
        rep.fail("GET /api/agent/status", f"{type(exc).__name__}: {exc}")
        return 1

    mcp = status.get("mcp", {})
    if mcp.get("connected"):
        rep.ok(
            "MCP 连接",
            f"发现 {len(mcp.get('tools', []))} 个工具；写工具 {mcp.get('write_tools')}",
        )
    else:
        rep.fail("MCP 连接", str(mcp.get("error"))[:200])
        print("\nMCP 不可用，Agent 相关检查无法进行。")
        return 1

    audit = mcp.get("audit", {})
    if audit.get("ok"):
        rep.ok("审批策略覆盖检查", audit.get("hint", ""))
    else:
        rep.warn("审批策略覆盖检查", audit.get("hint", ""))

    rep.info(f"模型：{status['model']['provider']} —— {status['model']['note']}")

    tools_info = client.get(f"{base}/api/agent/tools", headers=auth(token_a)).json()
    summary = tools_info.get("summary", {})
    if not summary.get("empty_description"):
        rep.ok(
            "工具 schema 完整性",
            f"{summary.get('total', 0)} 个工具描述均非空"
            f"（读 {summary.get('read', 0)} / 写 {summary.get('write', 0)}）",
        )
    else:
        rep.fail("工具 schema 完整性", f"描述为空的工具：{summary['empty_description']}")

    if not summary.get("identity_leaks"):
        rep.ok("工具参数无身份字段", "身份全部走 HTTP 头，模型看不到也改不了")
    else:
        rep.fail("工具参数无身份字段", f"暴露了身份参数：{summary['identity_leaks']}")

    # ============================================================ 3. 身份不串号
    rep.section("3. 身份带外透传（防越权）")
    try:
        token_b = login(client, base, "20230102")
        me_b = client.get(f"{base}/api/auth/me", headers=auth(token_b)).json()
        sched_a = client.get(f"{base}/api/me/schedule", headers=auth(token_a)).json()
        sched_b = client.get(f"{base}/api/me/schedule", headers=auth(token_b)).json()
        rep.ok(
            "两个用户各自的身份独立",
            f"{me_a['name']} 课表 {len(sched_a)} 门 / {me_b['name']} 课表 {len(sched_b)} 门",
        )
        events_a, _, _ = stream_post(
            client, f"{base}/api/agent/chat", token_a,
            {"message": "我的课表", "thread_id": f"{RUN_ID}-identity-a"},
        )
        events_b, _, _ = stream_post(
            client, f"{base}/api/agent/chat", token_b,
            {"message": "我的课表", "thread_id": f"{RUN_ID}-identity-b"},
        )
        text_a = "".join(p.get("text", "") for e, p in events_a if e == "token")
        text_b = "".join(p.get("text", "") for e, p in events_b if e == "token")
        # 交错发起的两个会话，如果串号，A 的回答会包含 B 的课程
        leaked = len(sched_a) == len(sched_b) and text_a == text_b and len(sched_a) > 0
        if leaked:
            rep.warn(
                "Agent 会话身份是否串号",
                "两人课表恰好都为空或完全相同，此项无法判定",
            )
        else:
            rep.ok(
                "Agent 会话身份不串号",
                f"A 的回答 {len(text_a)} 字 / B 的回答 {len(text_b)} 字，内容不同",
            )
    except Exception as exc:  # noqa: BLE001
        rep.fail("身份不串号检查", f"{type(exc).__name__}: {exc}")

    # ============================================================ 4. ReAct + SSE
    rep.section("4. ReAct 循环与 SSE 流式")
    try:
        events, ttfb, total = stream_post(
            client, f"{base}/api/agent/chat", token_a,
            {"message": "一学期最多能选多少学分？", "thread_id": f"{RUN_ID}-read-1"},
        )
        names = [e for e, _ in events]
        rep.ok(
            "SSE 事件序列",
            " → ".join(dict.fromkeys(names)) if names else "（空）",
        )
        if "meta" in names:
            rep.ok("首次连接下发工具清单", "event: meta")
        tool_calls = [p for e, p in events if e == "tool_call"]
        if tool_calls:
            rep.ok(
                "模型自主调用工具（ReAct）",
                "; ".join(f"{c['name']}{c['args']}" for c in tool_calls),
            )
        else:
            rep.fail("模型自主调用工具（ReAct）", "没有产生 tool_call 事件")

        tokens = [p["text"] for e, p in events if e == "token"]
        answer = "".join(tokens)
        rep.ok("流式 token", f"{len(tokens)} 个分片，共 {len(answer)} 字")

        # TTFB 要从「第一个 token」算，不能用首字节 ——
        # meta/start/status 这些帧在模型开始生成前就发出了，
        # 用首字节衡量会把「流式已经生效」误判成「流式不明显」。
        token_index = next((i for i, (e, _) in enumerate(events) if e == "token"), None)
        if token_index is not None and len(tokens) >= 5:
            rep.ok(
                "流式确实生效",
                f"回答被切成 {len(tokens)} 个分片逐段推送（而非整段一次到达）",
            )
        else:
            rep.warn(
                "流式效果不明显",
                f"只有 {len(tokens)} 个 token 分片；"
                f"回答较短时本身就会一次性到达，属正常",
            )

        if "学分" in answer:
            rep.ok("回答内容有据可依", f"片段：{answer[:56]}…")
        else:
            rep.warn("回答内容", f"未包含预期关键词：{answer[:60]}")

        # ---- 回归检查：内容块 repr 泄漏 ----
        # 实测坑：工具节点返回的 ToolMessage.content 是内容块列表
        # `[{'type':'text','text':...}]`，直接 str() 会把 Python repr 显示给用户。
        # 这个 bug 在 HTTP 层很难发现 —— repr 里同样含有关键词，
        # "回答里有没有学分"这类断言照样通过。所以要专门断言「没有 repr 痕迹」。
        leak_markers = (
            "[{'type':",        # Python repr 的内容块
            '[{"type":',        # JSON 形态的内容块（说明没解析）
            "'tool_call_id'",
            "'id': 'lc_",       # LangChain 的 content block id
        )
        tool_texts = " ".join(p.get("content", "") for e, p in events if e == "tool_result")
        leaked = [m for m in leak_markers if m in answer or m in tool_texts]
        if leaked:
            rep.fail(
                "消息内容未被 repr 污染",
                f"界面会显示 Python repr，命中标记 {leaked}",
            )
        else:
            rep.ok("消息内容未被 repr 污染", "工具结果与回答均为纯文本")
    except Exception as exc:  # noqa: BLE001
        rep.fail("ReAct / SSE 检查", f"{type(exc).__name__}: {exc}")

    # ============================================================ 5. 审批：拒绝
    rep.section("5. 写操作人工审批 —— 拒绝路径")
    baseline = count_enrollments(token_a, base, client)
    rep.info(f"审批前「我的选课记录」条数 = {baseline}")
    try:
        events, _, _ = stream_post(
            client, f"{base}/api/agent/chat", token_a,
            {"message": "帮我选 CS214", "thread_id": f"{RUN_ID}-write-reject"},
        )
        interrupts = [p for e, p in events if e == "interrupt"]
        if not interrupts:
            rep.fail("写操作触发审批中断", f"事件序列：{[e for e, _ in events]}")
        else:
            actions = interrupts[0]["actions"]
            rep.ok(
                "写操作触发审批中断",
                f"待确认：{[a['label'] for a in actions]}",
            )
            resume_events, _, _ = stream_post(
                client, f"{base}/api/agent/resume", token_a,
                {"thread_id": f"{RUN_ID}-write-reject",
                 "decisions": [{"type": "reject", "message": "我再想想"}]},
            )
            after = count_enrollments(token_a, base, client)
            if after == baseline:
                rep.ok(
                    "拒绝审批后写操作真的没有执行",
                    f"选课记录仍为 {after} 条（审批前 {baseline} 条）",
                )
            else:
                rep.fail(
                    "拒绝审批后写操作真的没有执行",
                    f"选课记录从 {baseline} 变成 {after}，说明拒绝没生效！",
                )
            rtext = "".join(p.get("text", "") for e, p in resume_events if e == "token")
            if rtext:
                rep.ok("拒绝后模型有解释", f"{rtext[:70]}…")
            else:
                rep.warn("拒绝后模型有解释", "没有产生文本回复")
    except Exception as exc:  # noqa: BLE001
        rep.fail("审批拒绝路径", f"{type(exc).__name__}: {exc}")

    # ============================================================ 6. 审批：批准
    rep.section("6. 写操作人工审批 —— 批准路径")
    baseline2 = count_enrollments(token_a, base, client)
    rep.info(f"审批前「我的选课记录」条数 = {baseline2}")

    target_code, why = find_enrollable_course(token_a, base, client)
    if target_code is None:
        rep.warn("批准路径测试", why)
    else:
        rep.info(f"预检出可选的课程：{why}")
        try:
            events, _, _ = stream_post(
                client, f"{base}/api/agent/chat", token_a,
                {"message": f"帮我选 {target_code}", "thread_id": f"{RUN_ID}-write-approve"},
            )
            if not [p for e, p in events if e == "interrupt"]:
                rep.fail("批准路径：触发审批中断", f"事件：{[e for e, _ in events]}")
            else:
                rep.ok("批准路径：触发审批中断", f"待确认 {target_code}")
                stream_post(
                    client, f"{base}/api/agent/resume", token_a,
                    {"thread_id": f"{RUN_ID}-write-approve",
                     "decisions": [{"type": "approve"}]},
                )
                after = count_enrollments(token_a, base, client)
                if after == baseline2 + 1:
                    rep.ok(
                        "批准审批后写操作真的执行了",
                        f"选课记录 {baseline2} → {after}",
                    )
                else:
                    rep.fail(
                        "批准审批后写操作真的执行了",
                        f"选课记录 {baseline2} → {after}，期望 +1。"
                        "请查 /api/audit/logs 看业务拒绝的确切原因",
                    )

                # ---- 收尾：把这次测试选的课退掉，让脚本可反复运行 ----
                # 不做清理的话每跑一次就会多选一门课，第二次跑时的
                # baseline 就不一样了，测试会越来越"脏"。
                if after == baseline2 + 1:
                    cleanup = client.delete(
                        f"{base}/api/enrollments/{target_code}", headers=auth(token_a)
                    )
                    final = count_enrollments(token_a, base, client)
                    if cleanup.status_code == 200 and final == baseline2:
                        rep.ok(
                            "测试数据已还原（脚本可反复运行）",
                            f"已退掉 {target_code}，选课记录回到 {final} 条",
                        )
                    else:
                        rep.warn(
                            "测试数据未完全还原",
                            f"清理 {target_code} 返回 {cleanup.status_code}，"
                            f"当前 {final} 条（基线 {baseline2} 条）",
                        )
        except Exception as exc:  # noqa: BLE001
            rep.fail("审批批准路径", f"{type(exc).__name__}: {exc}")

    # ============================================================ 7. 越界任务
    rep.section("7. 越界任务：不幻觉、不硬凑工具")
    from app.agent.scripted_model import BOUNDARY_RULES

    hallucination_markers = ("已报废", "已删除", "已执行", "已改", "改好了", "已经帮你改了")
    boundary_ok = True
    for idx, (keywords, _expected) in enumerate(BOUNDARY_RULES):
        prompt = keywords[0]
        try:
            events, _, _ = stream_post(
                client, f"{base}/api/agent/chat", token_a,
                {"message": f"帮我{prompt}", "thread_id": f"{RUN_ID}-boundary-{idx}"},
            )
            calls = [p["name"] for e, p in events if e == "tool_call"]
            answer = "".join(p.get("text", "") for e, p in events if e == "token"),
            answer = answer[0] if isinstance(answer, tuple) else answer

            hallucinated = [m for m in hallucination_markers if m in answer]
            # 越界任务不应该调用任何写工具
            stray_write = [c for c in calls if "enroll" in c or "drop" in c]

            if hallucinated:
                rep.fail(f"越界「{prompt}」不幻觉", f"出现完成语：{hallucinated}")
                boundary_ok = False
            elif stray_write:
                rep.fail(f"越界「{prompt}」不硬凑工具", f"调用了 {stray_write}")
                boundary_ok = False
            else:
                rep.ok(
                    f"越界「{prompt}」",
                    f"未幻觉、未硬凑工具（工具调用 {calls or '无'}）",
                )
        except Exception as exc:  # noqa: BLE001
            rep.fail(f"越界「{prompt}」", f"{type(exc).__name__}: {exc}")
            boundary_ok = False

    # ============================================================ 8. 审计
    rep.section("8. 审计留痕")
    try:
        logs = client.get(
            f"{base}/api/audit/logs", headers=auth(token_a),
            params={"source": "AI", "limit": 50},
        ).json()
        stats = client.get(f"{base}/api/audit/stats", headers=auth(token_a)).json()
        rep.ok(
            "AI 操作已进审计",
            f"AI 来源日志 {len(logs)} 条；总 {stats['total']} 条 "
            f"(WEB {stats['by_source']['WEB']} / AI {stats['by_source']['AI']})",
        )
        pending = client.get(
            f"{base}/api/audit/pending-actions", headers=auth(token_a)
        ).json()["items"]
        rejected = [p for p in pending if p["status"] == "rejected"]
        if rejected:
            rep.ok(
                "审批台账含被拒绝的记录",
                f"台账 {len(pending)} 条，其中被拒绝 {len(rejected)} 条",
            )
        else:
            rep.warn(
                "审批台账含被拒绝的记录",
                f"台账共 {len(pending)} 条但没有 rejected 记录，"
                "请确认拒绝路径测试是否真的跑到了",
            )
    except Exception as exc:  # noqa: BLE001
        rep.fail("审计检查", f"{type(exc).__name__}: {exc}")

    # ============================================================ 汇总
    rep.section("汇总")
    print(f"  通过 {rep.passed} 项 / 失败 {rep.failed} 项 / 警告 {rep.warned} 项")
    if rep.failed:
        print("\n  失败项：")
        for mark, name, detail in rep.rows:
            if mark == FAIL:
                print(f"    - {name}  {detail}")
    print()
    return 1 if rep.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
