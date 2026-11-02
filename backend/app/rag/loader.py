"""知识库加载与分块。

分块策略：**按 Markdown 标题切，标题路径带进正文**。
理由是校园规章制度这类文档，答案的语境高度依赖标题（「退课」这一节里的
「不收取任何费用」脱离标题就没有意义），把标题路径拼回正文能明显提升召回质量。
超长小节再按段落二次切分，并保留轻微重叠。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..config import KB_DIR

MAX_CHUNK_CHARS = 700
OVERLAP_CHARS = 80

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass
class Chunk:
    chunk_id: str
    source_file: str
    title: str
    content: str
    metadata: dict = field(default_factory=dict)


def _split_long(text: str) -> list[str]:
    """超长小节按空行分段累积，控制在 MAX_CHUNK_CHARS 内并保留重叠。"""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        if not buf:
            buf = para
        elif len(buf) + len(para) + 2 <= MAX_CHUNK_CHARS:
            buf = f"{buf}\n\n{para}"
        else:
            chunks.append(buf)
            tail = buf[-OVERLAP_CHARS:] if len(buf) > OVERLAP_CHARS else buf
            buf = f"{tail}\n\n{para}"
    if buf:
        chunks.append(buf)
    return chunks or [text]


def parse_markdown(path: Path) -> list[Chunk]:
    """把一份 Markdown 拆成带标题路径的块。"""
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()

    doc_title = ""
    sections: list[tuple[str, list[str]]] = []
    current_path: list[str] = []
    current_title = ""
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_lines, current_title
        body = "\n".join(current_lines).strip()
        if body:
            sections.append((current_title or doc_title, body.split("\n")))
        current_lines = []

    for line in lines:
        m = _HEADING_RE.match(line)
        if not m:
            current_lines.append(line)
            continue
        level = len(m.group(1))
        text = m.group(2).strip()
        if level == 1 and not doc_title:
            doc_title = text
            current_path = [text]
            continue
        flush()
        # 维护标题层级栈
        current_path = current_path[: level - 1] + [text]
        current_title = " > ".join(current_path)
    flush()

    chunks: list[Chunk] = []
    for title, body_lines in sections:
        body = "\n".join(body_lines).strip()
        if len(body) < 30:  # 太短的多半是纯标题或残余，跳过
            continue
        pieces = _split_long(body) if len(body) > MAX_CHUNK_CHARS else [body]
        for idx, piece in enumerate(pieces):
            # 标题路径拼回正文 —— 这是本分块策略的核心
            content = f"【{title}】\n{piece}"
            digest = hashlib.md5(f"{path.name}:{title}:{idx}".encode()).hexdigest()[:16]
            chunks.append(
                Chunk(
                    chunk_id=f"{path.stem}-{digest}",
                    source_file=path.name,
                    title=title,
                    content=content,
                    metadata={"source_file": path.name, "title": title, "part": idx},
                )
            )
    return chunks


def load_all_chunks(kb_dir: Path | None = None) -> list[Chunk]:
    directory = kb_dir or KB_DIR
    if not directory.exists():
        return []
    chunks: list[Chunk] = []
    for path in sorted(directory.glob("*.md")):
        chunks.extend(parse_markdown(path))
    return chunks
