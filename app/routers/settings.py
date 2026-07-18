"""系统设置路由"""
import os
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from app.routers.auth import get_current_user
from app.config import settings, BASE_DIR

router = APIRouter(prefix="/settings", tags=["系统设置"])
templates = Jinja2Templates(directory="app/templates")


def check_auth(request: Request):
    if not get_current_user(request):
        return RedirectResponse("/login", status_code=303)
    return None


def _read_env() -> dict:
    """读取 .env 文件内容为字典"""
    env_path = BASE_DIR / ".env"
    result = {
        "WECOM_WEBHOOK_URL": "",
        "SERVERCHAN_SEND_KEY": "",
        "PUSHPLUS_TOKEN": "",
        "SMS_SECRET_ID": "",
        "SMS_SECRET_KEY": "",
        "SMS_SDK_APP_ID": "",
        "SMS_TEMPLATE_ID": "",
        "SMS_SIGN_NAME": "",
        "WECOM_CORP_ID": "",
        "WECOM_AGENT_SECRET": "",
        "WECOM_AGENT_ID": "",
        "LLM_API_KEY": "",
        "LLM_API_BASE": "https://api.deepseek.com/v1",
        "LLM_MODEL": "deepseek-chat",
        "ADMIN_PASSWORD": "",
    }
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    if key in result:
                        result[key] = value
    return result


def _write_env(updates: dict):
    """更新 .env 文件中的配置项"""
    env_path = BASE_DIR / ".env"

    # 读取现有内容
    lines = []
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    # 更新或追加配置
    updated_keys = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=")[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
                updated_keys.add(key)
                continue
        new_lines.append(line)

    # 追加未更新的新键
    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    # 同步更新内存中的 settings
    for key, value in updates.items():
        if hasattr(settings, key):
            setattr(settings, key, value)


@router.get("")
async def settings_page(request: Request):
    """设置页面"""
    if r := check_auth(request): return r

    env_data = _read_env()

    return templates.TemplateResponse("settings.html", {
        "request": request,
        "active_page": "settings",
        "env_data": env_data,
        "settings": settings,
    })


@router.post("/notifications")
async def save_notification_settings(
    request: Request,
    wecom_webhook_url: str = Form(""),
    serverchan_key: str = Form(""),
    pushplus_token: str = Form(""),
):
    """保存通知推送设置"""
    if r := check_auth(request): return r

    updates = {
        "WECOM_WEBHOOK_URL": wecom_webhook_url.strip(),
        "SERVERCHAN_SEND_KEY": serverchan_key.strip(),
        "PUSHPLUS_TOKEN": pushplus_token.strip(),
    }
    _write_env(updates)

    return RedirectResponse("/settings?saved=1", status_code=303)


@router.post("/tenant-notifications")
async def save_tenant_notification_settings(
    request: Request,
    sms_secret_id: str = Form(""),
    sms_secret_key: str = Form(""),
    sms_sdk_app_id: str = Form(""),
    sms_template_id: str = Form(""),
    sms_sign_name: str = Form(""),
    wecom_corp_id: str = Form(""),
    wecom_agent_secret: str = Form(""),
    wecom_agent_id: str = Form(""),
):
    """保存直推租客的通知设置（短信 + 企微→微信）"""
    if r := check_auth(request): return r

    updates = {
        "SMS_SECRET_ID": sms_secret_id.strip(),
        "SMS_SECRET_KEY": sms_secret_key.strip(),
        "SMS_SDK_APP_ID": sms_sdk_app_id.strip(),
        "SMS_TEMPLATE_ID": sms_template_id.strip(),
        "SMS_SIGN_NAME": sms_sign_name.strip(),
        "WECOM_CORP_ID": wecom_corp_id.strip(),
        "WECOM_AGENT_SECRET": wecom_agent_secret.strip(),
        "WECOM_AGENT_ID": wecom_agent_id.strip(),
    }
    _write_env(updates)

    return RedirectResponse("/settings?saved=1", status_code=303)


@router.post("/ai")
async def save_ai_settings(
    request: Request,
    llm_api_key: str = Form(""),
    llm_api_base: str = Form("https://api.deepseek.com/v1"),
    llm_model: str = Form("deepseek-chat"),
):
    """保存 AI 设置"""
    if r := check_auth(request): return r

    updates = {
        "LLM_API_KEY": llm_api_key.strip(),
        "LLM_API_BASE": llm_api_base.strip(),
        "LLM_MODEL": llm_model.strip(),
        "LLM_VISION_MODEL": llm_model.strip(),
    }
    _write_env(updates)

    return RedirectResponse("/settings?saved=1", status_code=303)


@router.post("/password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    """修改登录密码"""
    if r := check_auth(request): return r

    if new_password != confirm_password:
        return templates.TemplateResponse("settings.html", {
            "request": request,
            "active_page": "settings",
            "error": "两次输入的新密码不一致",
            "env_data": _read_env(),
            "settings": settings,
        })

    if new_password.strip() == "":
        return templates.TemplateResponse("settings.html", {
            "request": request,
            "active_page": "settings",
            "error": "密码不能为空",
            "env_data": _read_env(),
            "settings": settings,
        })

    updates = {"ADMIN_PASSWORD": new_password.strip()}
    _write_env(updates)

    return RedirectResponse("/settings?password_changed=1", status_code=303)
