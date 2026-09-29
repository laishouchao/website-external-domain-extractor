from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from app.config import ACCESS_TOKEN_EXPIRE_MINUTES
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token
)
from app.db import crud

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ==================== Request / Response Schemas ====================

class LoginRequest(BaseModel):
    username: str = Field(..., description="登录用户名")
    password: str = Field(..., description="登录密码")


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., description="旧密码")
    new_password: str = Field(..., min_length=6, description="新密码（至少6位）")


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, description="初始密码")
    nickname: Optional[str] = Field("", description="用户昵称")
    role: Optional[str] = Field("admin", description="角色: admin / operator / viewer")
    is_active: Optional[bool] = Field(True, description="是否启用")


class UpdateUserRequest(BaseModel):
    nickname: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    new_password: Optional[str] = None


# ==================== Dependencies ====================

async def get_current_user(
    request: Request,
    token_query: Optional[str] = Query(None, alias="token")
) -> dict:
    """
    Authenticate request via:
    1. Authorization Header: Bearer <token>
    2. Query param: ?token=<token> (for SSE / direct window.open exports)
    3. Cookie: access_token
    """
    token: Optional[str] = None

    # 1. Authorization Header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()

    # 2. Query param (fallback for EventSource and download links)
    if not token and token_query:
        token = token_query.strip()

    # 3. Cookie (fallback for browser navigations)
    if not token:
        token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录后再进行操作",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录凭证已过期或无效，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    username: Optional[str] = payload.get("sub")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭据",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = crud.get_user_by_username(username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户账号不存在或已被删除",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该用户账号已被停用，请联系管理员",
        )

    return user


async def get_current_admin(
    current_user: dict = Depends(get_current_user)
) -> dict:
    """Ensure current user has admin role."""
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="权限不足，仅超级管理员可执行此操作"
        )
    return current_user


# ==================== Auth Endpoints ====================

@router.post("/login")
def login(req: LoginRequest, response: Response):
    """User login endpoint returning JWT access token."""
    username = req.username.strip()
    password = req.password

    user = crud.get_user_by_username(username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )

    if not verify_password(password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )

    if not user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该账号已被停用，无法登录"
        )

    # Update last login time
    crud.update_user_last_login(user["id"])

    # Generate token
    token_payload = {
        "sub": user["username"],
        "uid": user["id"],
        "role": user.get("role", "admin")
    }
    access_token = create_access_token(token_payload)

    # Set cookie for browser downloads / SSE convenience
    response.set_cookie(
        key="access_token",
        value=access_token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=False,
        samesite="lax",
        path="/"
    )

    safe_user = {
        "id": user["id"],
        "username": user["username"],
        "nickname": user.get("nickname") or user["username"],
        "role": user.get("role", "admin"),
        "created_at": user.get("created_at"),
        "last_login_at": user.get("last_login_at")
    }

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": safe_user
    }


@router.post("/logout")
def logout(response: Response):
    """User logout endpoint clearing session cookie."""
    response.delete_cookie(key="access_token", path="/")
    return {"message": "已成功退出登录"}


@router.get("/me")
def get_current_user_profile(current_user: dict = Depends(get_current_user)):
    """Return currently authenticated user profile."""
    return {
        "id": current_user["id"],
        "username": current_user["username"],
        "nickname": current_user.get("nickname") or current_user["username"],
        "role": current_user.get("role", "admin"),
        "is_active": current_user.get("is_active", True),
        "created_at": current_user.get("created_at"),
        "updated_at": current_user.get("updated_at"),
        "last_login_at": current_user.get("last_login_at")
    }


@router.post("/change-password")
def change_password(
    req: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user)
):
    """Change current user's password."""
    if not verify_password(req.old_password, current_user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前旧密码输入错误"
        )

    if req.old_password == req.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新密码不能与旧密码相同"
        )

    new_hash = hash_password(req.new_password)
    crud.update_user_password(current_user["id"], new_hash)
    return {"message": "密码修改成功，请妥善保管"}


# ==================== User Management (Admin Only) ====================

@router.get("/users")
def list_system_users(_admin: dict = Depends(get_current_admin)):
    """List all registered system users (admin only)."""
    return {"users": crud.list_users()}


@router.post("/users")
def create_system_user(
    req: CreateUserRequest,
    _admin: dict = Depends(get_current_admin)
):
    """Create a new user (admin only)."""
    existing = crud.get_user_by_username(req.username)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"用户名 '{req.username}' 已被占用"
        )

    pwd_hash = hash_password(req.password)
    new_user = crud.create_user(
        username=req.username,
        password_hash=pwd_hash,
        nickname=req.nickname or req.username,
        role=req.role or "admin",
        is_active=req.is_active if req.is_active is not None else True
    )
    return {"user": new_user, "message": "用户创建成功"}


@router.put("/users/{user_id}")
def update_system_user(
    user_id: int,
    req: UpdateUserRequest,
    _admin: dict = Depends(get_current_admin)
):
    """Update user information or reset password (admin only)."""
    user = crud.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="目标用户不存在")

    updates = {}
    if req.nickname is not None:
        updates["nickname"] = req.nickname.strip()
    if req.role is not None:
        updates["role"] = req.role.strip()
    if req.is_active is not None:
        updates["is_active"] = req.is_active

    if updates:
        crud.update_user_profile(user_id, updates)

    if req.new_password:
        if len(req.new_password) < 6:
            raise HTTPException(status_code=400, detail="新密码长度不能少于6位")
        crud.update_user_password(user_id, hash_password(req.new_password))

    return {"user": crud.get_user_by_id(user_id), "message": "用户信息更新成功"}


@router.delete("/users/{user_id}")
def delete_system_user(
    user_id: int,
    admin: dict = Depends(get_current_admin)
):
    """Delete a user (admin only, cannot delete self)."""
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="不能删除当前登录的管理员账号")

    try:
        success = crud.delete_user(user_id)
        if not success:
            raise HTTPException(status_code=404, detail="用户不存在")
        return {"message": "用户已成功删除"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
