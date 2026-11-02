"""选课 / 退课接口。

**这是 MCP 工具服务唯一会写的两个接口**，也是 Agent 写操作的落点。

两个刻意的设计：
1. 以 `course_code`（如 CS202）而不是数据库 id 作为对外标识 —— 模型和人都更容易用对。
2. 拒绝返回 HTTP 409 + 结构化 body（含 `code`），而不是 400。
   Agent 拿到 `COURSE_FULL` 这类机器可读的 code 才能给出准确解释，
   而不是把一整段报错原文复述给用户。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..services import BusinessError, drop_course, enroll_course, get_course_by_code

router = APIRouter(prefix="/api/enrollments", tags=["选课"])


class EnrollRequest(BaseModel):
    course_code: str


def _resolve_source(x_source: str | None, x_mcp_ticket: str | None) -> str:
    """判断这次写操作是人在页面上点的，还是 Agent 代办的。"""
    if x_source and x_source.upper() == "AI":
        return "AI"
    if x_mcp_ticket:
        return "AI"
    return "WEB"


@router.post("", summary="选课")
def enroll(
    payload: EnrollRequest,
    x_source: str | None = Header(default=None, description="WEB / AI"),
    x_mcp_ticket: str | None = Header(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    source = _resolve_source(x_source, x_mcp_ticket)
    try:
        course = get_course_by_code(db, payload.course_code.strip().upper())
    except BusinessError as exc:
        raise HTTPException(status_code=404, detail=exc.to_dict()) from exc

    try:
        return enroll_course(db, user, course.id, source=source)
    except BusinessError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=exc.to_dict()
        ) from exc


@router.delete("/{course_code}", summary="退课")
def drop(
    course_code: str,
    x_source: str | None = Header(default=None),
    x_mcp_ticket: str | None = Header(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    source = _resolve_source(x_source, x_mcp_ticket)
    try:
        course = get_course_by_code(db, course_code.strip().upper())
    except BusinessError as exc:
        raise HTTPException(status_code=404, detail=exc.to_dict()) from exc

    try:
        return drop_course(db, user, course.id, source=source)
    except BusinessError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=exc.to_dict()
        ) from exc
