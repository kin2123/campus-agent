"""审计日志与审批台账接口。

这是「AI 的每一次尝试都留痕」的对外出口，也是答辩/论文里最有说服力的一页：
能看到 Agent 调了什么工具、结果如何、被拒绝的操作是什么、AI 代办了哪些业务。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import AuditLog, PendingAction, User
from ..schemas import AuditLogOut

router = APIRouter(prefix="/api/audit", tags=["审计"])


@router.get("/logs", response_model=list[AuditLogOut], summary="操作日志")
def logs(
    source: str | None = Query(None, description="WEB / AI，不传则全部"),
    result: str | None = Query(None, description="SUCCESS / REJECTED / FAILED"),
    action: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    scope: str = Query("mine", description="mine=只看自己，all=全部（需管理员）"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[AuditLogOut]:
    stmt = select(AuditLog).order_by(desc(AuditLog.created_at), desc(AuditLog.id))
    if scope != "all" or user.role != "admin":
        stmt = stmt.where(AuditLog.user_id == user.id)
    if source:
        stmt = stmt.where(AuditLog.source == source)
    if result:
        stmt = stmt.where(AuditLog.result == result)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    rows = db.scalars(stmt.limit(limit)).all()
    return [AuditLogOut.model_validate(r) for r in rows]


@router.get("/stats", summary="审计统计（AI 与人工操作对比）")
def stats(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    base = select(AuditLog)
    if user.role != "admin":
        base = base.where(AuditLog.user_id == user.id)

    def count(**filters) -> int:
        stmt = base
        for key, value in filters.items():
            stmt = stmt.where(getattr(AuditLog, key) == value)
        return len(db.scalars(stmt).all())

    return {
        "total": count(),
        "by_source": {
            "WEB": count(source="WEB"),
            "AI": count(source="AI"),
        },
        "by_result": {
            "SUCCESS": count(result="SUCCESS"),
            "REJECTED": count(result="REJECTED"),
            "FAILED": count(result="FAILED"),
        },
        "ai_success": count(source="AI", result="SUCCESS"),
        "ai_rejected": count(source="AI", result="REJECTED"),
    }


@router.get("/pending-actions", summary="Agent 写操作审批台账")
def pending_actions(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """审批台账。**被拒绝的操作也在这里** —— 这是完整证据链。"""
    stmt = (
        select(PendingAction)
        .order_by(desc(PendingAction.created_at), desc(PendingAction.id))
        .limit(limit)
    )
    if user.role != "admin":
        stmt = stmt.where(PendingAction.user_id == user.id)
    rows = db.scalars(stmt).all()
    return {
        "items": [
            {
                "id": r.id,
                "thread_id": r.thread_id,
                "tool_name": r.tool_name,
                "args": r.args,
                "description": r.description,
                "status": r.status,
                "result": r.result,
                "error": r.error,
                "created_at": r.created_at.isoformat(),
                "decided_at": r.decided_at.isoformat() if r.decided_at else None,
                "executed_at": r.executed_at.isoformat() if r.executed_at else None,
            }
            for r in rows
        ]
    }
