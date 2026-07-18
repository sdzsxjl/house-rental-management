"""
通知推送服务 — 支持多渠道全自动发送催租消息

推送到房东（提醒房东去催）：
  1. 企业微信群机器人 — 推送到企微群，免费
  2. PushPlus — 推送到房东个人微信，免费 (200条/天)
  3. Server酱 — 推送到房东个人微信，免费 (5条/天)

推送到租客（全自动，无需房东转发）⭐：
  4. 腾讯云短信 — 直接发到租客手机号，¥0.045/条
  5. 企业微信客户联系 — 直接发到租客的微信App，免费

配置方式：
  - 在系统「设置」页面填写对应渠道的配置
  - 或直接编辑 .env 文件
"""

import json
import hashlib
import hmac
import time
import random
import httpx
from typing import Optional
from dataclasses import dataclass
from app.config import settings


@dataclass
class PushResult:
    success: bool
    channel: str
    message: str


# ═══════════════════════════════════════════════════════════
# 推送到房东（提醒房东）
# ═══════════════════════════════════════════════════════════

async def push_wecom_webhook(webhook_url: str, text: str) -> PushResult:
    """企业微信群机器人 → 推送到企微群"""
    if not webhook_url:
        return PushResult(False, "企业微信群机器人", "未配置 Webhook URL")

    payload = {"msgtype": "markdown", "markdown": {"content": text}}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=payload)
            data = resp.json()
            if data.get("errcode") == 0:
                return PushResult(True, "企业微信群机器人", "发送成功")
            return PushResult(False, "企业微信群机器人", f"失败: {data.get('errmsg')}")
    except Exception as e:
        return PushResult(False, "企业微信群机器人", f"异常: {str(e)}")


async def push_pushplus(token: str, title: str, content: str) -> PushResult:
    """PushPlus → 推送到房东个人微信"""
    if not token:
        return PushResult(False, "PushPlus", "未配置 Token")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post("https://www.pushplus.plus/send", json={
                "token": token, "title": title, "content": content, "template": "html",
            })
            data = resp.json()
            if data.get("code") == 200:
                return PushResult(True, "PushPlus", "发送成功")
            return PushResult(False, "PushPlus", f"失败: {data.get('msg')}")
    except Exception as e:
        return PushResult(False, "PushPlus", f"异常: {str(e)}")


async def push_serverchan(send_key: str, title: str, content: str) -> PushResult:
    """Server酱 → 推送到房东个人微信"""
    if not send_key:
        return PushResult(False, "Server酱", "未配置 SendKey")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"https://sctapi.ftqq.com/{send_key}.send",
                data={"title": title, "desp": content},
            )
            data = resp.json()
            if data.get("code") == 0:
                return PushResult(True, "Server酱", "发送成功")
            return PushResult(False, "Server酱", f"失败: {data.get('message')}")
    except Exception as e:
        return PushResult(False, "Server酱", f"异常: {str(e)}")


# ═══════════════════════════════════════════════════════════
# 推送到租客（全自动，租客直接收到）⭐
# ═══════════════════════════════════════════════════════════

# ─── 腾讯云短信 ──────────────────────────────────────────
# 使用说明：
#   1. 注册腾讯云 → 开通「短信 SMS」服务
#   2. 创建签名（如"房东通知"）和应用
#   3. 创建短信模板，如：
#      "{1}您好，{2}月份房租¥{3}已到缴费期，请在{4}号前缴纳。如有问题请联系房东。"
#   4. 获取 SDK AppID、SecretId、SecretKey
#   模板变量: {1}=租客名, {2}=月份, {3}=金额, {4}=截止日期

async def push_sms_to_tenant(
    phone: str,
    tenant_name: str,
    rent_month: str,
    amount: float,
    due_day: int,
    days_overdue: int = 0,
) -> PushResult:
    """
    通过腾讯云短信发送催租通知到租客手机

    配置项（.env）:
      SMS_SECRET_ID=你的腾讯云SecretId
      SMS_SECRET_KEY=你的腾讯云SecretKey
      SMS_SDK_APP_ID=你的短信应用ID
      SMS_TEMPLATE_ID=你的短信模板ID
      SMS_SIGN_NAME=你的短信签名
    """
    secret_id = getattr(settings, "SMS_SECRET_ID", "")
    secret_key = getattr(settings, "SMS_SECRET_KEY", "")
    sdk_app_id = getattr(settings, "SMS_SDK_APP_ID", "")
    template_id = getattr(settings, "SMS_TEMPLATE_ID", "")
    sign_name = getattr(settings, "SMS_SIGN_NAME", "")

    if not all([secret_id, secret_key, sdk_app_id, template_id, sign_name]):
        return PushResult(False, "短信(租客)", "腾讯云短信未完整配置")

    # 腾讯云短信 API v3 签名
    endpoint = "sms.tencentcloudapi.com"
    timestamp = int(time.time())
    date_str = time.strftime("%Y-%m-%d", time.gmtime(timestamp))

    # 请求体
    payload = json.dumps({
        "PhoneNumberSet": [f"+86{phone}"],
        "SmsSdkAppId": sdk_app_id,
        "SignName": sign_name,
        "TemplateId": template_id,
        "TemplateParamSet": [
            tenant_name,           # {1}
            rent_month.replace("-", "年") + "月",  # {2}
            str(int(amount)),      # {3}
            str(due_day),          # {4}
        ],
    })

    # 腾讯云 API v3 签名算法
    service = "sms"
    action = "SendSms"
    canonical_headers = f"content-type:application/json\nhost:{endpoint}\n"
    signed_headers = "content-type;host"
    hashed_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    canonical_request = (
        "POST\n/\n\n"
        f"{canonical_headers}\n"
        f"{signed_headers}\n"
        f"{hashed_payload}"
    )

    algorithm = "TC3-HMAC-SHA256"
    credential_scope = f"{date_str}/{service}/tc3_request"
    hashed_canonical_request = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    string_to_sign = f"{algorithm}\n{timestamp}\n{credential_scope}\n{hashed_canonical_request}"

    def _sign(key, msg):
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    secret_date = _sign(("TC3" + secret_key).encode("utf-8"), date_str)
    secret_service = _sign(secret_date, service)
    secret_signing = _sign(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization = (
        f"{algorithm} Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    headers = {
        "Authorization": authorization,
        "Content-Type": "application/json",
        "Host": endpoint,
        "X-TC-Action": action,
        "X-TC-Timestamp": str(timestamp),
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"https://{endpoint}", headers=headers, content=payload)
            data = resp.json()
            status_set = data.get("Response", {}).get("SendStatusSet", [])
            if status_set and status_set[0].get("Code") == "Ok":
                return PushResult(True, "短信(租客)", f"已发送至 {phone}")
            error = data.get("Response", {}).get("Error", {})
            return PushResult(False, "短信(租客)", f"失败: {error.get('Message', '未知')}")
    except Exception as e:
        return PushResult(False, "短信(租客)", f"异常: {str(e)}")


# ─── 企业微信「客户联系」→ 直达租客微信App ────────────────
# 使用说明：
#   1. 在企业微信管理后台 → 客户联系 → 开启「客户联系」功能
#   2. 在「应用管理」中创建一个自建应用，获取 CorpId、AgentId、Secret
#   3. 房东在企微App中添加租客为「客户」（加微信好友）
#   4. 系统通过 API 直接向租客的微信发送消息
#   租客在个人微信上收到消息！完全免费！


async def _get_wecom_access_token(corp_id: str, secret: str) -> Optional[str]:
    """获取企业微信 access_token"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
                params={"corpid": corp_id, "corpsecret": secret},
            )
            data = resp.json()
            if data.get("errcode") == 0:
                return data["access_token"]
            return None
    except Exception:
        return None


async def push_wecom_to_tenant(
    tenant_name: str,
    tenant_phone: str,
    tenant_wechat_id: str,
    message_text: str,
    rent_month: str,
) -> PushResult:
    """
    通过企业微信「客户联系」API 直接发送消息到租客的个人微信

    配置项（.env）:
      WECOM_CORP_ID=企业ID
      WECOM_AGENT_SECRET=自建应用的Secret
      WECOM_AGENT_ID=自建应用的AgentId

    前提条件:
      - 房东在企微App中已经添加该租客为「客户」（外部联系人）
      - 系统通过手机号/微信号查找该外部联系人并发送消息
    """
    corp_id = getattr(settings, "WECOM_CORP_ID", "")
    agent_secret = getattr(settings, "WECOM_AGENT_SECRET", "")
    agent_id_str = getattr(settings, "WECOM_AGENT_ID", "")

    if not all([corp_id, agent_secret, agent_id_str]):
        return PushResult(False, "企微→租客微信", "企业微信客户联系未完整配置")

    # 获取 token
    token = await _get_wecom_access_token(corp_id, agent_secret)
    if not token:
        return PushResult(False, "企微→租客微信", "获取access_token失败")

    # 先尝试通过手机号查找外部联系人
    external_userid = None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # 通过手机号查找
            search_resp = await client.post(
                "https://qyapi.weixin.qq.com/cgi-bin/externalcontact/get_by_phone",
                params={"access_token": token},
                json={"phone": tenant_phone},
            )
            search_data = search_resp.json()
            if search_data.get("errcode") == 0:
                external_userid = search_data.get("external_userid")
    except Exception:
        pass

    if not external_userid:
        return PushResult(
            False, "企微→租客微信",
            f"未找到租客 {tenant_name}({tenant_phone}) 的企业微信外部联系人。"
            f"请先在企微App中添加该租客为外部联系人。"
        )

    # 发送文本消息到租客微信
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            msg_resp = await client.post(
                "https://qyapi.weixin.qq.com/cgi-bin/externalcontact/message/send",
                params={"access_token": token},
                json={
                    "to_external_userid": [external_userid],
                    "agentid": int(agent_id_str),
                    "text": {"content": message_text},
                },
            )
            msg_data = msg_resp.json()
            if msg_data.get("errcode") == 0:
                return PushResult(True, "企微→租客微信", f"已发送至 {tenant_name} 的微信")
            return PushResult(False, "企微→租客微信", f"失败: {msg_data.get('errmsg')}")
    except Exception as e:
        return PushResult(False, "企微→租客微信", f"异常: {str(e)}")


# ═══════════════════════════════════════════════════════════
# 组合发送
# ═══════════════════════════════════════════════════════════

async def send_reminder_to_all_channels(
    title: str,
    content: str,
) -> list[PushResult]:
    """向所有已配置的房东通知渠道发送汇总消息"""
    results = []
    if getattr(settings, "WECOM_WEBHOOK_URL", ""):
        results.append(await push_wecom_webhook(settings.WECOM_WEBHOOK_URL, content))
    if getattr(settings, "PUSHPLUS_TOKEN", ""):
        results.append(await push_pushplus(settings.PUSHPLUS_TOKEN, title, content))
    if getattr(settings, "SERVERCHAN_SEND_KEY", ""):
        results.append(await push_serverchan(settings.SERVERCHAN_SEND_KEY, title, content))
    return results


async def send_reminder_to_tenant_directly(
    tenant_name: str,
    tenant_phone: str,
    tenant_wechat_id: str,
    room_code: str,
    reminder_text: str,
    rent_month: str,
    monthly_rent: float,
    due_day: int,
    days_overdue: int,
) -> list[PushResult]:
    """
    向单个租客直接推送催租消息（短信 + 企微客户联系）
    这才是真正的「全自动」——租客直接收到，房东不用动手
    """
    results = []

    # 1. 短信 → 直接发到租客手机
    results.append(await push_sms_to_tenant(
        phone=tenant_phone,
        tenant_name=tenant_name,
        rent_month=rent_month,
        amount=monthly_rent,
        due_day=due_day,
        days_overdue=days_overdue,
    ))

    # 2. 企业微信客户联系 → 直接发到租客的个人微信
    results.append(await push_wecom_to_tenant(
        tenant_name=tenant_name,
        tenant_phone=tenant_phone,
        tenant_wechat_id=tenant_wechat_id,
        message_text=reminder_text,
        rent_month=rent_month,
    ))

    return results


async def push_to_landlord_summary(
    gentle: list, warning: list, overdue: list,
    rent_month: str,
) -> list[PushResult]:
    """推送催租汇总给房东"""
    total = len(gentle) + len(warning) + len(overdue)

    lines = [f"## 📋 {rent_month} 催租日报\n"]

    if overdue:
        lines.append(f"### 🚨 严重逾期 ({len(overdue)}户)")
        for r in overdue:
            lines.append(
                f"- **{r['tenant'].name}** ({r['room'].full_room_code}) "
                f"逾期 {r['days_overdue']} 天 · ¥{r['contract'].monthly_rent:.0f}"
            )
        lines.append("")

    if warning:
        lines.append(f"### ⚠️ 催缴警告 ({len(warning)}户)")
        for r in warning:
            lines.append(
                f"- **{r['tenant'].name}** ({r['room'].full_room_code}) "
                f"逾期 {r['days_overdue']} 天 · ¥{r['contract'].monthly_rent:.0f}"
            )
        lines.append("")

    if gentle:
        lines.append(f"### 💬 温和提醒 ({len(gentle)}户)")
        for r in gentle:
            lines.append(
                f"- **{r['tenant'].name}** ({r['room'].full_room_code}) "
                f"· ¥{r['contract'].monthly_rent:.0f}"
            )
        lines.append("")

    if total == 0:
        lines.append("✅ 本月所有租客已全部缴清！")

    content = "\n".join(lines)
    title = f"催租日报 - {rent_month}（共{total}户待催）"

    return await send_reminder_to_all_channels(title, content)
