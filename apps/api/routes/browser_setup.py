"""浏览器登录初始化 API（本机 profile 缓存）。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.fetch_worker.login_init import (
    cancel_login_init,
    clear_and_relogin,
    complete_login_init,
    get_login_init_status,
    refresh_login_verify,
    start_login_init,
)

router = APIRouter(prefix="/browser", tags=["browser"])


class LoginInitRequest(BaseModel):
    profile_name: str = Field(default="hr_default", description="浏览器 profile 名称")


@router.get("/login/status")
async def login_status(profile: str = "hr_default"):
    return await get_login_init_status(profile)


@router.post("/login/start")
async def login_start(body: LoginInitRequest | None = None):
    """打开猎聘登录页（不清除已有缓存）。"""
    profile = body.profile_name if body else "hr_default"
    return await start_login_init(profile)


@router.post("/login/relogin")
async def login_relogin(body: LoginInitRequest | None = None):
    """清除登录缓存并打开猎聘登录页。"""
    profile = body.profile_name if body else "hr_default"
    return await clear_and_relogin(profile)


@router.post("/login/complete")
async def login_complete():
    try:
        return await complete_login_init()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/login/cancel")
async def login_cancel():
    return await cancel_login_init()


@router.post("/login/verify")
async def login_verify(body: LoginInitRequest | None = None):
    profile = body.profile_name if body else "hr_default"
    try:
        return await refresh_login_verify(profile)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
