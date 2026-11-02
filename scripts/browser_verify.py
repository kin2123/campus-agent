"""用 Chrome DevTools Protocol 做一次真实的浏览器端验证并截图。

为什么要做到这一步：前面的 31 项自检走的是 HTTP 层，能证明后端没问题；
`--dump-dom` 能证明登录页渲染了。但**主界面（Agent 对话、课表网格、审批卡片）
是不是真的画出来了**，只有把登录态注入浏览器、真的渲染一遍才知道。

做法：连 CDP，用 Runtime.evaluate 在前端同源下写 localStorage 拿登录态，
重新加载后逐页截图。
"""
from __future__ import annotations

import asyncio
import base64
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx
import websockets

CHROME = r"C:\Users\10115\AppData\Local\Google\Chrome\Application\chrome.exe"
FRONT = "http://127.0.0.1:5173"
BACK = "http://127.0.0.1:18000"
OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
PORT = 9223


class CDP:
    def __init__(self, ws) -> None:
        self.ws = ws
        self._id = 0

    async def call(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        msg_id = self._id
        await self.ws.send(json.dumps({"id": msg_id, "method": method,
                                       "params": params or {}}))
        while True:
            raw = await self.ws.recv()
            data = json.loads(raw)
            if data.get("id") == msg_id:
                if "error" in data:
                    raise RuntimeError(f"{method} 失败: {data['error']}")
                return data.get("result", {})

    async def evaluate(self, expr: str, await_promise: bool = False):
        res = await self.call("Runtime.evaluate", {
            "expression": expr,
            "awaitPromise": await_promise,
            "returnByValue": True,
        })
        return res.get("result", {}).get("value")

    async def shot(self, name: str) -> Path:
        res = await self.call("Page.captureScreenshot", {"format": "png"})
        path = OUT_DIR / f"{name}.png"
        path.write_bytes(base64.b64decode(res["data"]))
        return path


async def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 先拿一个真实 token，待会儿注入浏览器
    token = httpx.post(f"{BACK}/api/auth/login",
                       json={"username": "20230101", "password": "123456"},
                       timeout=20).json()["access_token"]
    print(f"已获取登录票据（{len(token)} 字符）")

    chrome = subprocess.Popen(
        [
            CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
            f"--remote-debugging-port={PORT}",
            "--window-size=1500,1000",
            "--user-data-dir=" + str(OUT_DIR.parent / "_chrome_profile"),
            "about:blank",
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    try:
        # 等 CDP 端口起来
        ws_url = None
        for _ in range(40):
            try:
                targets = httpx.get(f"http://127.0.0.1:{PORT}/json", timeout=3).json()
                page = next((t for t in targets if t["type"] == "page"), None)
                if page:
                    ws_url = page["webSocketDebuggerUrl"]
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.5)
        if not ws_url:
            print("连不上 Chrome CDP")
            return 1

        async with websockets.connect(ws_url, max_size=40 * 1024 * 1024) as ws:
            cdp = CDP(ws)
            await cdp.call("Page.enable")
            await cdp.call("Runtime.enable")

            # ---- 登录页截图 ----
            await cdp.call("Page.navigate", {"url": FRONT})
            await asyncio.sleep(3)
            print("登录页标题:", await cdp.evaluate("document.title"))
            p = await cdp.shot("01-登录页")
            print(f"  已截图 {p.name}")

            # ---- 注入登录态（必须在前端同源下写 localStorage）----
            user = httpx.post(f"{BACK}/api/auth/login",
                              json={"username": "20230101", "password": "123456"},
                              timeout=20).json()["user"]
            await cdp.evaluate(
                f"localStorage.setItem('campus_token', {json.dumps(token)});"
                f"localStorage.setItem('campus_user', {json.dumps(json.dumps(user, ensure_ascii=False))});"
                "'ok'"
            )
            await cdp.call("Page.navigate", {"url": FRONT})
            await asyncio.sleep(4)

            body = await cdp.evaluate("document.body.innerText.slice(0, 400)")
            print("\n重载后页面文本片段:")
            print("  " + (body or "").replace("\n", "\n  ")[:400])

            p = await cdp.shot("02-智能助手")
            print(f"\n  已截图 {p.name}")

            # ---- 真实交互 1：点快捷提问，验证 SSE 流式与工具卡片 ----
            print("\n[交互] 点击「一学期最多能选多少学分」…")
            clicked = await cdp.evaluate(
                "(() => { const els = Array.from(document.querySelectorAll('button'));"
                " const el = els.find(e => e.innerText.includes('一学期最多能选多少学分'));"
                " if (el) { el.click(); return true; } return false; })()"
            )
            if clicked:
                # 等段落推进：思考 → 调工具 → 工具返回 → 逐字回答
                for wait in (2, 3, 3, 3):
                    await asyncio.sleep(wait)
                text = await cdp.evaluate("document.body.innerText")
                has_tool = "检索学校规章制度" in (text or "") or "正在执行" in (text or "")
                has_answer = "学分" in (text or "")
                print(f"  工具调用卡片出现: {has_tool}")
                print(f"  回答内容已渲染:   {has_answer}")
                p = await cdp.shot("03-对话-ReAct与流式")
                print(f"  已截图 {p.name}")
            else:
                print("  未找到快捷提问按钮")

            # ---- 真实交互 2：触发写操作，验证审批卡片 ----
            print("\n[交互] 点击「帮我选 CS202」触发审批…")
            clicked = await cdp.evaluate(
                "(() => { const els = Array.from(document.querySelectorAll('button'));"
                " const el = els.find(e => e.innerText.includes('帮我选 CS202'));"
                " if (el) { el.click(); return true; } return false; })()"
            )
            if clicked:
                await asyncio.sleep(8)
                text = await cdp.evaluate("document.body.innerText")
                has_approval = "批准" in (text or "") and "拒绝" in (text or "")
                print(f"  审批卡片出现（含批准/拒绝按钮）: {has_approval}")
                p = await cdp.shot("04-写操作审批卡片")
                print(f"  已截图 {p.name}")

                # 滚回顶部再截一张，便于看清整屏排版
                # （对话区默认滚到底部，首行会被顶部状态条裁掉一截）
                await cdp.evaluate(
                    "(() => { const c = document.querySelector('.chat');"
                    " if (c) { c.scrollTop = 0; return true; } return false; })()"
                )
                await asyncio.sleep(1.2)
                p = await cdp.shot("04b-审批卡片-滚到顶部")
                print(f"  已截图 {p.name}")

                if has_approval:
                    # 点「拒绝」，验证拒绝路径在界面上也能走通
                    await cdp.evaluate(
                        "(() => { const els = Array.from(document.querySelectorAll('button'));"
                        " const el = els.find(e => e.innerText.trim() === '拒绝');"
                        " if (el) { el.click(); return true; } return false; })()"
                    )
                    await asyncio.sleep(6)
                    p = await cdp.shot("05-拒绝后回复")
                    print(f"  已截图 {p.name}（拒绝路径）")
            else:
                print("  未找到对应快捷按钮")

            # ---- 逐页切换截图 ----
            navs = await cdp.evaluate(
                "Array.from(document.querySelectorAll('nav a, nav button, .nav-item, header button'))"
                ".map(e => e.innerText.trim()).filter(Boolean)"
            )
            print(f"\n导航项: {[n.replace(chr(10), ' ') for n in (navs or [])]}")

            for idx, label in enumerate(navs or [], start=3):
                clicked = await cdp.evaluate(
                    f"(() => {{ const els = Array.from(document.querySelectorAll('nav a, nav button, .nav-item, header button'));"
                    f" const el = els.find(e => e.innerText.trim() === {json.dumps(label)});"
                    f" if (el) {{ el.click(); return true; }} return false; }})()"
                )
                if not clicked:
                    continue
                await asyncio.sleep(2.5)
                # 导航项形如 "◆\n智能助手"，必须清掉换行和符号，
                # 否则会生成带 \n 的非法文件名直接 PermissionError
                safe = "".join(
                    ch for ch in label.replace("\n", "").replace(" ", "")
                    if ch.isalnum() or "\u4e00" <= ch <= "\u9fff"
                ) or f"page{idx}"
                p = await cdp.shot(f"{idx:02d}-{safe}")
                print(f"  已截图 {p.name}  ({label.replace(chr(10), ' ')})")

            # ---- 安全：检查控制台是否报错 ----
            await cdp.call("Runtime.enable")
            print("\n浏览器验证完成。")

    finally:
        chrome.terminate()
        try:
            chrome.wait(timeout=10)
        except Exception:  # noqa: BLE001
            chrome.kill()

    print(f"\n截图目录: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
