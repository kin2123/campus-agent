"""SQLAlchemy 2.0 数据模型。

设计要点：
- Enrollment 对 (user_id, course_id) 建唯一约束，退课后重选是「更新状态」而非插新行，
  这样 Agent 反复选/退不会把表撑爆。
- Course.enrolled_count 是并发占座的计数器，由条件 UPDATE 原子维护；
  不能退化成「数一下 enrollments」的 Python 属性，否则并发会超卖。
- AuditLog 记录 source=WEB/AI，这是「AI 的操作同样受审计」的落地方式。
- PendingAction.result/error/executed_at 记录审批后的真实执行结果，
  approved 只代表用户同意，不代表工具执行成功。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(64))
    # student / teacher / admin
    role: Mapped[str] = mapped_column(String(16), default="student")
    student_no: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    major: Mapped[str | None] = mapped_column(String(64), nullable=True)
    grade: Mapped[str | None] = mapped_column(String(16), nullable=True)
    class_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    enrollments: Mapped[list["Enrollment"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    teacher_name: Mapped[str] = mapped_column(String(64))
    credits: Mapped[float] = mapped_column(Float, default=2.0)
    capacity: Mapped[int] = mapped_column(Integer, default=50)
    semester: Mapped[str] = mapped_column(String(16), default="2026-2027-1")
    # 必修 / 专业选修 / 通识 / 实践
    category: Mapped[str] = mapped_column(String(16), default="专业选修")
    # 上课时间：weekday 1-7，slot 1-10（每节 45 分钟）
    weekday: Mapped[int] = mapped_column(Integer, default=1)
    start_slot: Mapped[int] = mapped_column(Integer, default=1)
    end_slot: Mapped[int] = mapped_column(Integer, default=2)
    location: Mapped[str] = mapped_column(String(64), default="待定")
    exam_type: Mapped[str] = mapped_column(String(16), default="考查")
    # 先修课程代码，逗号分隔；空串表示无先修要求
    prerequisite_codes: Mapped[str] = mapped_column(String(128), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    # 已占座人数。必须是数据库列而不是「数一下 enrollments」的 Python 属性：
    # 后者在并发选课时会先读后写，两个请求可能同时读到最后一个空位。
    enrolled_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    enrollments: Mapped[list["Enrollment"]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )

    @property
    def remaining(self) -> int:
        return max(self.capacity - self.enrolled_count, 0)


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("user_id", "course_id", name="uq_user_course"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    # enrolled（在读）/ completed（已修完有成绩）/ dropped（已退）
    status: Mapped[str] = mapped_column(String(16), default="enrolled")
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(8), default="WEB")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped["User"] = relationship(back_populates="enrollments")
    course: Mapped["Course"] = relationship(back_populates="enrollments")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    username: Mapped[str] = mapped_column(String(64), default="anonymous")
    action: Mapped[str] = mapped_column(String(32), index=True)
    target_type: Mapped[str] = mapped_column(String(32), default="")
    target_id: Mapped[str] = mapped_column(String(32), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    # WEB / AI —— 区分是人在页面点的，还是 Agent 代办的
    source: Mapped[str] = mapped_column(String(8), default="WEB", index=True)
    # SUCCESS / REJECTED / FAILED
    result: Mapped[str] = mapped_column(String(16), default="SUCCESS", index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class KnowledgeChunk(Base):
    """知识库分块的元数据镜像。

    Chroma 已经是向量库，这里额外存一份「原文分块」是为了：
    ① 索引失败时能对比；② 前端能列出知识库来源；③ 评测 RAG 召回时做基线核对。
    """

    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    chunk_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    source_file: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PendingAction(Base):
    """Agent 写操作的审批台账。

    即使审批被拒绝也要落库 —— 这是「AI 尝试过什么」的完整证据链。
    """

    __tablename__ = "pending_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(64))
    args: Mapped[str] = mapped_column(Text, default="{}")
    description: Mapped[str] = mapped_column(Text, default="")
    # pending / approved / rejected
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # 执行结果：SUCCESS / FAILED / REJECTED / NOT_EXECUTED
    result: Mapped[str | None] = mapped_column(String(16), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
