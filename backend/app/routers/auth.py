"""认证接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..schemas import LoginRequest, LoginResponse, UserOut
from ..security import create_access_token, verify_password
from ..services import write_audit

router = APIRouter(prefix="/api/auth", tags=["认证"])


@router.post("/login", response_model=LoginResponse, summary="登录")
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(payload.password, user.hashed_password):
        # 不区分「用户不存在」和「密码错误」，避免账号枚举
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误"
        )
    token = create_access_token(user.id, user.username, user.role)
    write_audit(db, user=user, action="login", source="WEB")
    return LoginResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut, summary="当前登录用户")
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)


@router.get("/demo-accounts", summary="演示账号列表")
def demo_accounts() -> dict:
    """方便体验：项目自带三个角色的演示账号。"""
    return {
        "accounts": [
            {"username": "20230101", "password": "123456", "role": "student",
             "name": "张思远", "note": "主演示账号，已有历史成绩"},
            {"username": "20230102", "password": "123456", "role": "student",
             "name": "李佳琪", "note": "空课表，适合演示选课"},
            {"username": "T2001", "password": "123456", "role": "teacher", "name": "王海宁"},
            {"username": "admin", "password": "123456", "role": "admin", "name": "教务管理员"},
        ]
    }
