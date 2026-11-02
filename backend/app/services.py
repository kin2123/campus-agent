"""业务服务层 —— 全系统唯一的业务规则真相源。

关键设计：**Agent 和页面调用的是同一套函数**。
MCP 工具服务通过 HTTP 回调这里的 REST 接口，而不是自己重写一份规则，
所以「容量满」「时间冲突」这类判断永远不会出现两处规则漂移。

写操作用条件 UPDATE 原子占座/释放，避免并发超卖；
业务写入与审计日志放在同一个事务里提交，避免「选课成功但审计丢失」。
"""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from .config import settings
from .models import AuditLog, Course, Enrollment, User


class BusinessError(Exception):
    """可预期的业务拒绝。带机器可读的 code，方便前端/Agent 分类处理。"""

    def __init__(self, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.extra}


# --------------------------------------------------------------------------- 审计


def write_audit(
    db: Session,
    *,
    user: User | None,
    action: str,
    target_type: str = "",
    target_id: str | int = "",
    detail: Any = None,
    source: str = "WEB",
    result: str = "SUCCESS",
    message: str = "",
    commit: bool = True,
) -> AuditLog:
    log = AuditLog(
        user_id=user.id if user else None,
        username=user.username if user else "anonymous",
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        detail=json.dumps(detail, ensure_ascii=False) if detail is not None else "",
        source=source,
        result=result,
        message=message,
    )
    db.add(log)
    if commit:
        db.commit()
        db.refresh(log)
    else:
        # 与业务写入放在同一事务里提交，避免「选课成功但审计丢失」。
        db.flush()
    return log


# --------------------------------------------------------------------------- 查询


def list_courses(
    db: Session,
    *,
    keyword: str | None = None,
    category: str | None = None,
    semester: str | None = None,
    only_available: bool = False,
) -> list[Course]:
    stmt = select(Course)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            Course.name.like(like)
            | Course.code.like(like)
            | Course.teacher_name.like(like)
        )
    if category:
        stmt = stmt.where(Course.category == category)
    if semester:
        stmt = stmt.where(Course.semester == semester)
    courses = list(db.scalars(stmt.order_by(Course.code)))
    if only_available:
        courses = [c for c in courses if c.remaining > 0]
    return courses


def get_course(db: Session, course_id: int) -> Course:
    course = db.get(Course, course_id)
    if course is None:
        raise BusinessError("COURSE_NOT_FOUND", f"课程 id={course_id} 不存在")
    return course


def get_course_by_code(db: Session, code: str) -> Course:
    course = db.scalar(select(Course).where(Course.code == code))
    if course is None:
        raise BusinessError("COURSE_NOT_FOUND", f"课程代码 {code} 不存在")
    return course


def _slots_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start <= b_end and b_start <= a_end


def get_my_schedule(db: Session, user: User) -> list[Course]:
    stmt = (
        select(Course)
        .join(Enrollment, Enrollment.course_id == Course.id)
        .where(Enrollment.user_id == user.id, Enrollment.status == "enrolled")
        .order_by(Course.weekday, Course.start_slot)
    )
    return list(db.scalars(stmt))


def get_my_enrollments(db: Session, user: User) -> list[tuple[Enrollment, Course]]:
    stmt = (
        select(Enrollment, Course)
        .join(Course, Course.id == Enrollment.course_id)
        .where(Enrollment.user_id == user.id, Enrollment.status == "enrolled")
        .order_by(Course.weekday, Course.start_slot)
    )
    return [(e, c) for e, c in db.execute(stmt).all()]


def get_my_grades(db: Session, user: User) -> list[tuple[Enrollment, Course]]:
    """只返回已有成绩的记录 —— 未出分的不算成绩。

    包含 `completed`（历史已修）与 `enrolled`（本学期已出分）两种状态。
    """
    stmt = (
        select(Enrollment, Course)
        .join(Course, Course.id == Enrollment.course_id)
        .where(
            Enrollment.user_id == user.id,
            Enrollment.status.in_(["enrolled", "completed"]),
            Enrollment.score.is_not(None),
        )
        .order_by(Course.semester, Course.code)
    )
    return [(e, c) for e, c in db.execute(stmt).all()]


def compute_gpa(rows: list[tuple[Enrollment, Course]]) -> dict[str, Any]:
    """按学分加权算平均分，并换算 4.0 制绩点。"""
    total_credit = 0.0
    weighted = 0.0
    grade_point_sum = 0.0
    for enrollment, course in rows:
        if enrollment.score is None:
            continue
        credit = float(course.credits)
        total_credit += credit
        weighted += float(enrollment.score) * credit
        # 常见换算：90+ = 4.0，60 以下 = 0
        score = float(enrollment.score)
        if score >= 90:
            gp = 4.0
        elif score >= 60:
            gp = (score - 50) / 10.0
        else:
            gp = 0.0
        grade_point_sum += gp * credit
    return {
        "total_credit": round(total_credit, 1),
        "average": round(weighted / total_credit, 2) if total_credit else 0.0,
        "gpa": round(grade_point_sum / total_credit, 3) if total_credit else 0.0,
        "course_count": len(rows),
    }


def sync_enrollment_counts(db: Session) -> int:
    """按 enrollments 真相源重算 courses.enrolled_count。

    seed 直接插选课记录，不走 enroll_course，所以启动/补数据后必须校准一次。
    """
    counts = dict(
        db.execute(
            select(Enrollment.course_id, func.count(Enrollment.id))
            .where(Enrollment.status == "enrolled")
            .group_by(Enrollment.course_id)
        ).all()
    )
    courses = list(db.scalars(select(Course)))
    for course in courses:
        course.enrolled_count = counts.get(course.id, 0)
    db.commit()
    return len(courses)


# --------------------------------------------------------------------------- 写操作

# 同一学生的「校验 + 写入」必须串行：时间冲突和学分上限都是「先读后写」，
# 只靠条件 UPDATE 只能防超卖，防不住两个并发请求同时读到旧课表后都通过校验。
# 后端是单进程，MCP 也通过 HTTP 回调这里写库，所以进程内按用户加锁即可覆盖
# 全部写入路径；跨进程的座位争抢仍由条件 UPDATE 兜底。
_USER_WRITE_LOCKS = tuple(threading.Lock() for _ in range(64))


def _user_write_lock(user_id: int) -> threading.Lock:
    return _USER_WRITE_LOCKS[user_id % len(_USER_WRITE_LOCKS)]


def _validate_enroll(
    db: Session,
    user: User,
    course: Course,
    existing: Enrollment | None,
    reject: Callable[..., None],
) -> None:
    """选课前置校验。每次事务重试都会重新调用，必须读最新已提交数据。"""
    if existing is not None and existing.status == "enrolled":
        reject("ALREADY_ENROLLED", f"你已经选过《{course.name}》了，无需重复选课")

    # 已修且合格不能重复选（培养方案第 4 条限制）
    if existing is not None and existing.status == "completed" and (existing.score or 0) >= 60:
        reject(
            "ALREADY_PASSED",
            f"《{course.name}》你已修过且成绩合格（{existing.score} 分），不能重复选课",
            score=existing.score,
        )

    if course.remaining <= 0:
        reject(
            "COURSE_FULL",
            f"《{course.name}》容量已满（{course.enrolled_count}/{course.capacity}）",
            enrolled=course.enrolled_count, capacity=course.capacity,
        )

    # —— 时间冲突检查 ——
    for other in get_my_schedule(db, user):
        if other.weekday != course.weekday:
            continue
        if _slots_overlap(course.start_slot, course.end_slot, other.start_slot, other.end_slot):
            reject(
                "TIME_CONFLICT",
                f"时间冲突：《{course.name}》与已选课程《{other.name}》"
                f"都在周{course.weekday} 第{course.start_slot}-{course.end_slot}节",
                conflict_with=other.name,
            )

    # —— 先修课检查：必须已修且成绩 >= 60 ——
    prereq_codes = [c.strip() for c in (course.prerequisite_codes or "").split(",") if c.strip()]
    for code in prereq_codes:
        prereq = db.scalar(select(Course).where(Course.code == code))
        if prereq is None:
            continue
        record = db.scalar(
            select(Enrollment).where(
                Enrollment.user_id == user.id,
                Enrollment.course_id == prereq.id,
                Enrollment.status.in_(["enrolled", "completed"]),
            )
        )
        if record is None or record.score is None or record.score < 60:
            reject(
                "PREREQUISITE_NOT_MET",
                f"先修课未通过：选《{course.name}》需要先通过《{prereq.name}》"
                f"（{code}）且成绩≥60",
                prerequisite=prereq.name,
            )

    # —— 学分上限检查 ——
    current_credits = sum(float(c.credits) for c in get_my_schedule(db, user))
    if current_credits + float(course.credits) > settings.max_credits_per_semester:
        reject(
            "CREDIT_LIMIT_EXCEEDED",
            f"超出学分上限：当前已选 {current_credits} 学分，"
            f"加选《{course.name}》（{course.credits} 学分）会超过"
            f"{settings.max_credits_per_semester} 学分上限",
            current_credits=current_credits, limit=settings.max_credits_per_semester,
        )


def enroll_course(db: Session, user: User, course_id: int, source: str = "WEB") -> dict[str, Any]:
    """选课。所有拒绝路径都会写审计，方便复盘「AI 当时为什么被拒」。"""
    with _user_write_lock(user.id):
        return _enroll_course_locked(db, user, course_id, source)


def _enroll_course_locked(
    db: Session, user: User, course_id: int, source: str
) -> dict[str, Any]:
    try:
        course = get_course(db, course_id)
    except BusinessError as exc:
        write_audit(
            db, user=user, action="enroll", target_type="course", target_id=course_id,
            source=source, result="FAILED", message=exc.message,
        )
        raise

    # 路由层可能已经用同一个 session 读过课程，强制刷新余量，避免友好提示用旧值。
    db.refresh(course)

    course_code = course.code
    course_name = course.name
    course_label = f"{course_code} {course_name}"
    capacity = int(course.capacity)

    def reject(code: str, message: str, **extra: Any) -> None:
        write_audit(
            db, user=user, action="enroll", target_type="course",
            target_id=course_label, detail=extra,
            source=source, result="REJECTED", message=message,
        )
        raise BusinessError(code, message, **extra)

    def reject_after_rollback(code: str, message: str, **extra: Any) -> None:
        write_audit(
            db, user=user, action="enroll", target_type="course",
            target_id=course_label, detail=extra,
            source=source, result="REJECTED", message=message,
        )
        raise BusinessError(code, message, **extra)

    # —— 校验在重试循环内部：上一轮如果因并发回滚，必须重新读课表再判断 ——
    for attempt in range(3):
        existing = db.scalar(
            select(Enrollment).where(
                Enrollment.user_id == user.id,
                Enrollment.course_id == course_id,
            )
        )
        _validate_enroll(db, user, course, existing, reject)
        existing_id = existing.id if existing is not None else None

        try:
            # 容量检查只是友好提示，真正的并发闸门是条件 UPDATE：
            # 只有 enrolled_count < capacity 时才会加一。
            claimed = db.execute(
                update(Course)
                .where(Course.id == course_id, Course.enrolled_count < Course.capacity)
                .values(enrolled_count=Course.enrolled_count + 1)
            ).rowcount
            if not claimed:
                db.rollback()
                reject_after_rollback(
                    "COURSE_FULL",
                    f"《{course_name}》容量已满（{capacity}/{capacity}）",
                    enrolled=capacity, capacity=capacity,
                )

            if existing_id is None:
                db.add(
                    Enrollment(
                        user_id=user.id, course_id=course_id,
                        status="enrolled", source=source,
                    )
                )
            else:
                changed = db.execute(
                    update(Enrollment)
                    .where(
                        Enrollment.id == existing_id,
                        Enrollment.status != "enrolled",
                    )
                    .values(status="enrolled", source=source, score=None)
                ).rowcount
                if not changed:
                    db.rollback()
                    reject_after_rollback(
                        "ALREADY_ENROLLED",
                        f"你已经选过《{course_name}》了，无需重复选课",
                    )

            write_audit(
                db, user=user, action="enroll", target_type="course",
                target_id=course_label, detail={"course_id": course_id},
                source=source, result="SUCCESS", message=f"选课成功：《{course_name}》",
                commit=False,
            )
            db.commit()
            break
        except IntegrityError:
            # 同一用户并发选同一门课：唯一约束兜底，回滚已占的座位后再判断。
            db.rollback()
            row = db.scalar(
                select(Enrollment).where(
                    Enrollment.user_id == user.id,
                    Enrollment.course_id == course_id,
                )
            )
            if row is not None and row.status == "completed" and (row.score or 0) >= 60:
                reject_after_rollback(
                    "ALREADY_PASSED",
                    f"《{course_name}》你已修过且成绩合格（{row.score} 分），不能重复选课",
                    score=row.score,
                )
            if row is not None and row.status != "enrolled":
                existing_id = row.id
                continue
            reject_after_rollback(
                "ALREADY_ENROLLED",
                f"你已经选过《{course_name}》了，无需重复选课",
            )
        except OperationalError as exc:
            db.rollback()
            message = str(exc).lower()
            if "locked" not in message and "busy" not in message:
                raise
            time.sleep(0.05 * (attempt + 1))
    else:
        reject_after_rollback(
            "CONCURRENT_CONFLICT",
            "选课请求过于集中，请稍后重试",
            retryable=True,
        )

    db.refresh(course)
    return {
        "course_id": course_id,
        "course_code": course.code,
        "course_name": course.name,
        "credits": course.credits,
        "remaining": course.remaining,
        "message": f"选课成功：《{course.name}》（{course.code}），"
                   f"{course.credits} 学分，上课时间 周{course.weekday} "
                   f"第{course.start_slot}-{course.end_slot}节 {course.location}",
    }


def drop_course(db: Session, user: User, course_id: int, source: str = "WEB") -> dict[str, Any]:
    """退课。与选课共用同一把用户锁，避免选退交错读到中间状态。"""
    with _user_write_lock(user.id):
        return _drop_course_locked(db, user, course_id, source)


def _drop_course_locked(
    db: Session, user: User, course_id: int, source: str
) -> dict[str, Any]:
    try:
        course = get_course(db, course_id)
    except BusinessError as exc:
        write_audit(
            db, user=user, action="drop", target_type="course", target_id=course_id,
            source=source, result="FAILED", message=exc.message,
        )
        raise

    record = db.scalar(
        select(Enrollment).where(
            Enrollment.user_id == user.id, Enrollment.course_id == course_id
        )
    )

    if record is None or record.status != "enrolled":
        msg = f"你没有选《{course.name}》，无法退课"
        write_audit(
            db, user=user, action="drop", target_type="course",
            target_id=f"{course.code} {course.name}", source=source,
            result="REJECTED", message=msg,
        )
        raise BusinessError("NOT_ENROLLED", msg)

    if record.score is not None:
        msg = f"《{course.name}》已出成绩（{record.score}），成绩已归档，不能退课"
        write_audit(
            db, user=user, action="drop", target_type="course",
            target_id=f"{course.code} {course.name}", source=source,
            result="REJECTED", message=msg,
        )
        raise BusinessError("SCORE_ARCHIVED", msg)

    record_id = record.id
    course_code = course.code
    course_name = course.name
    course_label = f"{course_code} {course_name}"

    for attempt in range(3):
        try:
            # 条件更新保证同一个选课记录只会被退一次、只释放一个座位。
            changed = db.execute(
                update(Enrollment)
                .where(
                    Enrollment.id == record_id,
                    Enrollment.status == "enrolled",
                )
                .values(status="dropped")
            ).rowcount
            if not changed:
                db.rollback()
                msg = f"你没有选《{course_name}》，无法退课"
                write_audit(
                    db, user=user, action="drop", target_type="course",
                    target_id=course_label, source=source,
                    result="REJECTED", message=msg,
                )
                raise BusinessError("NOT_ENROLLED", msg)

            db.execute(
                update(Course)
                .where(Course.id == course_id, Course.enrolled_count > 0)
                .values(enrolled_count=Course.enrolled_count - 1)
            )
            write_audit(
                db, user=user, action="drop", target_type="course",
                target_id=course_label, detail={"course_id": course_id},
                source=source, result="SUCCESS", message=f"退课成功：《{course_name}》",
                commit=False,
            )
            db.commit()
            break
        except OperationalError as exc:
            db.rollback()
            message = str(exc).lower()
            if "locked" not in message and "busy" not in message:
                raise
            time.sleep(0.05 * (attempt + 1))
    else:
        write_audit(
            db, user=user, action="drop", target_type="course",
            target_id=course_label, source=source,
            result="FAILED", message="退课请求过于集中，请稍后重试",
        )
        raise BusinessError("CONCURRENT_CONFLICT", "退课请求过于集中，请稍后重试")

    db.refresh(course)
    return {
        "course_id": course_id,
        "course_code": course.code,
        "course_name": course.name,
        "remaining": course.remaining,
        "message": f"退课成功：《{course.name}》（{course.code}）已从课表移除",
    }
