"""登录认证"""
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from passlib.hash import bcrypt
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.config import settings

router = APIRouter(tags=["认证"])

# 简单的 session-like 认证：用 cookie 存储登录状态
SESSIONS: set[str] = set()


def get_current_user(request: Request) -> bool:
    """检查是否已登录"""
    return request.cookies.get("rental_session", "") in SESSIONS


def login_required(request: Request):
    """登录检查，未登录则重定向"""
    if not get_current_user(request):
        return None
    return True


@router.get("/login")
async def login_page(request: Request):
    """登录页面"""
    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory="app/templates")
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    """处理登录"""
    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory="app/templates")

    # 首次启动自动创建管理员
    user = db.query(User).filter(User.username == "admin").first()
    if not user:
        user = User(
            username="admin",
            password_hash=bcrypt.hash(settings.ADMIN_PASSWORD),
        )
        db.add(user)
        db.commit()

    if not bcrypt.verify(password, user.password_hash):
        return templates.TemplateResponse("login.html", {
            "request": request, "error": "密码错误"
        })

    # 生成简单 session token
    import secrets
    token = secrets.token_hex(32)
    SESSIONS.add(token)

    response = RedirectResponse("/", status_code=303)
    response.set_cookie("rental_session", token, httponly=True, max_age=86400 * 30)
    return response


@router.get("/logout")
async def logout(request: Request):
    """退出登录"""
    token = request.cookies.get("rental_session", "")
    SESSIONS.discard(token)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("rental_session")
    return response
