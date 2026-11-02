"""Pydantic 请求/响应模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., description="学号或用户名")
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    name: str
    role: str
    student_no: str | None = None
    major: str | None = None
    grade: str | None = None
    class_name: str | None = None

    model_config = {"from_attributes": True}


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class CourseOut(BaseModel):
    id: int
    code: str
    name: str
    teacher_name: str
    credits: float
    capacity: int
    semester: str
    category: str
    weekday: int
    start_slot: int
    end_slot: int
    location: str
    exam_type: str
    prerequisite_codes: str
    description: str
    enrolled_count: int
    remaining: int

    model_config = {"from_attributes": True}


class EnrollmentOut(BaseModel):
    course: CourseOut
    score: float | None = None
    source: str
    created_at: datetime


class GradeOut(BaseModel):
    course_code: str
    course_name: str
    credits: float
    semester: str
    score: float
    grade_point: float


class GradeSummary(BaseModel):
    total_credit: float
    average: float
    gpa: float
    course_count: int
    items: list[GradeOut]


class AuditLogOut(BaseModel):
    id: int
    username: str
    action: str
    target_type: str
    target_id: str
    detail: str
    source: str
    result: str
    message: str
    created_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeHit(BaseModel):
    chunk_id: str
    source_file: str
    title: str
    content: str
    score: float


class KnowledgeSearchResponse(BaseModel):
    query: str
    hits: list[KnowledgeHit]


class ChatRequest(BaseModel):
    message: str
    thread_id: str | None = Field(default=None, max_length=128)


class ApprovalDecision(BaseModel):
    type: Literal["approve", "reject"]
    message: str = ""


class ResumeRequest(BaseModel):
    thread_id: str = Field(..., max_length=128)
    decisions: list[ApprovalDecision] = Field(
        default_factory=lambda: [ApprovalDecision(type="reject")],
        min_length=1,
        max_length=20,
        description=(
            "逐项审批决定，顺序与 interrupt 事件里的 actions 一致。"
            "例如 [{'type':'approve'}, {'type':'reject','message':'理由'}]"
        ),
    )
