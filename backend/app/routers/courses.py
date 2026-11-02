"""课程与个人课表接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Course, User
from ..schemas import (
    CourseOut,
    EnrollmentOut,
    GradeOut,
    GradeSummary,
    UserOut,
)
from ..services import (
    BusinessError,
    compute_gpa,
    get_course_by_code,
    get_my_enrollments,
    get_my_grades,
    get_my_schedule,
    list_courses,
)

router = APIRouter(prefix="/api", tags=["课程"])


@router.get("/courses", response_model=list[CourseOut], summary="课程列表")
def get_courses(
    keyword: str | None = Query(None, description="按课程名/代码/教师模糊搜索"),
    category: str | None = Query(None, description="课程类别"),
    only_available: bool = Query(False, description="只看还有余量的课程"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[CourseOut]:
    courses = list_courses(
        db, keyword=keyword, category=category, only_available=only_available
    )
    return [CourseOut.model_validate(c) for c in courses]


@router.get("/courses/categories", response_model=list[str], summary="课程类别列表")
def get_categories(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[str]:
    rows = db.query(Course.category).distinct().all()
    return sorted({r[0] for r in rows})


@router.get("/courses/by-code/{code}", response_model=CourseOut, summary="按课程代码查详情")
def get_course_detail(
    code: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> CourseOut:
    try:
        course = get_course_by_code(db, code)
    except BusinessError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return CourseOut.model_validate(course)


@router.get("/me/schedule", response_model=list[CourseOut], summary="我的课表")
def my_schedule(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[CourseOut]:
    return [CourseOut.model_validate(c) for c in get_my_schedule(db, user)]


@router.get(
    "/me/enrollments", response_model=list[EnrollmentOut], summary="我的选课记录"
)
def my_enrollments(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[EnrollmentOut]:
    return [
        EnrollmentOut(
            course=CourseOut.model_validate(course),
            score=enrollment.score,
            source=enrollment.source,
            created_at=enrollment.created_at,
        )
        for enrollment, course in get_my_enrollments(db, user)
    ]


@router.get("/me/grades", response_model=GradeSummary, summary="我的成绩与绩点")
def my_grades(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> GradeSummary:
    rows = get_my_grades(db, user)
    summary = compute_gpa(rows)
    items = []
    for enrollment, course in rows:
        score = float(enrollment.score or 0)
        gp = 4.0 if score >= 90 else ((score - 50) / 10.0 if score >= 60 else 0.0)
        items.append(
            GradeOut(
                course_code=course.code,
                course_name=course.name,
                credits=float(course.credits),
                semester=course.semester,
                score=score,
                grade_point=round(gp, 2),
            )
        )
    return GradeSummary(items=items, **summary)
