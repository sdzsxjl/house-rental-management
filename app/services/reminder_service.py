"""催租服务：分级判断 + 文案生成"""
from datetime import date, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from app.models import Tenant, Contract, Payment, ReminderLog
from app.config import settings


# ─── 催租文案模板 ───────────────────────────────────────────

GENTLE_TEMPLATES = [
    "【温和提醒】{name}您好，今天是{month}月{due_day}号，到了本月交租日。请在方便时支付{month}月租金 ¥{amount}。如有困难请提前沟通，谢谢！🏠",
    "【交租提醒】{name}，{month}月份的房租 ¥{amount} 今天可以交了哦～收到请回复，谢谢配合 😊",
    "【温馨提示】{name}你好～又到月初了，{month}月租金 ¥{amount} 记得安排一下哈，感谢支持！",
]

WARNING_TEMPLATES = [
    "【催缴通知】{name}您好，{month}月租金 ¥{amount} 已超过缴费日 {days_overdue} 天。请尽快安排支付，避免产生滞纳金。如有特殊情况请及时说明。",
    "【租金催收】{name}，{month}月租金 ¥{amount} 还未收到，目前已逾期 {days_overdue} 天。请尽快缴纳，谢谢配合！",
]

OVERDUE_TEMPLATES = [
    "【严重逾期警告】{name}您好，您{month}月的租金 ¥{amount} 已逾期 {days_overdue} 天。根据合同约定，请于 3 日内结清欠款，否则将按合同条款处理。如有困难请务必主动联系沟通。",
    "【最后催缴】{name}，{month}月房租 ¥{amount} 已严重逾期 {days_overdue} 天。这是本月最后一次提醒，请立即缴纳以免影响您的租住权益。如有疑问请电联。",
]


def get_reminder_tier(contract: Contract, target_date: Optional[date] = None) -> tuple:
    """
    判断催租等级
    返回: (tier: str|None, days_overdue: int, due_date: date)
        tier: None=不需要, 'gentle'=温和, 'warning'=警告, 'overdue'=严重
    """
    if target_date is None:
        target_date = date.today()

    month_key = f"{target_date.year}-{target_date.month:02d}"
    due_day = min(contract.payment_due_day, 28)
    due_date = date(target_date.year, target_date.month, due_day)

    # 如果当前日期还没到缴费日（当月缴费日之前），不需要催
    if target_date < due_date:
        return None, 0, due_date

    days_overdue = (target_date - due_date).days

    if days_overdue >= settings.REMINDER_OVERDUE_OFFSET:
        return "overdue", days_overdue, due_date
    elif days_overdue >= settings.REMINDER_WARNING_OFFSET:
        return "warning", days_overdue, due_date
    elif days_overdue >= settings.REMINDER_GENTLE_OFFSET:
        return "gentle", days_overdue, due_date

    return None, days_overdue, due_date


def generate_reminder_text(
    tenant: Tenant,
    contract: Contract,
    tier: str,
    days_overdue: int,
    due_date: date,
    use_ai: bool = False,
) -> str:
    """
    生成催租文案
    - use_ai=False: 使用预设模板
    - use_ai=True: 调用 LLM 生成个性化文案
    """
    import random

    name = tenant.name
    month = due_date.month
    due_day = due_date.day
    amount = contract.monthly_rent

    if use_ai and settings.llm_enabled:
        return _ai_generate_reminder(tenant, contract, tier, days_overdue, month, amount)

    if tier == "gentle":
        return random.choice(GENTLE_TEMPLATES).format(
            name=name, month=month, due_day=due_day,
            amount=amount, days_overdue=days_overdue,
        )
    elif tier == "warning":
        return random.choice(WARNING_TEMPLATES).format(
            name=name, month=month, due_day=due_day,
            amount=amount, days_overdue=days_overdue,
        )
    else:  # overdue
        return random.choice(OVERDUE_TEMPLATES).format(
            name=name, month=month, due_day=due_day,
            amount=amount, days_overdue=days_overdue,
        )


def _ai_generate_reminder(
    tenant: Tenant,
    contract: Contract,
    tier: str,
    days_overdue: int,
    month: int,
    amount: float,
) -> str:
    """调用 LLM 生成个性化催租文案"""
    from openai import OpenAI

    client = OpenAI(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_API_BASE,
    )

    tier_desc = {
        "gentle": "温和的首次提醒，今天是缴费日",
        "warning": "稍微正式一点的催缴，已经过了缴费日几天",
        "overdue": "正式严肃的最后催缴，已经严重逾期",
    }

    prompt = f"""你是一位房东的助手，需要给租客发送催缴租金的微信消息。
租客姓名: {tenant.name}
月份: {month}月
租金金额: {amount}元
逾期天数: {days_overdue}天
语气要求: {tier_desc[tier]}

请写一条简洁自然的催租消息，控制在150字以内，语气友好但有效。直接输出消息文本，不要加引号。"""

    try:
        resp = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        # AI 失败则回退到模板
        import random
        if tier == "gentle":
            tmpl = GENTLE_TEMPLATES
        elif tier == "warning":
            tmpl = WARNING_TEMPLATES
        else:
            tmpl = OVERDUE_TEMPLATES
        return random.choice(tmpl).format(
            name=tenant.name, month=month, due_day=contract.payment_due_day,
            amount=amount, days_overdue=days_overdue,
        )


def run_daily_reminder_check(db: Session, target_date: Optional[date] = None) -> dict:
    """
    每日催租检查（由 APScheduler 调用）
    返回: {"gentle": [...], "warning": [...], "overdue": [...], "total": int}
    """
    if target_date is None:
        target_date = date.today()

    month_key = f"{target_date.year}-{target_date.month:02d}"

    # 获取所有有效合同
    active_contracts = db.query(Contract).filter(Contract.is_active == True).all()

    reminders = {"gentle": [], "warning": [], "overdue": [], "total": 0}

    for contract in active_contracts:
        tier, days_overdue, due_date = get_reminder_tier(contract, target_date)
        if tier is None:
            continue

        # 检查本月是否已经付过款
        paid = db.query(Payment).filter(
            Payment.tenant_id == contract.tenant_id,
            Payment.rent_month == month_key
        ).first()
        if paid:
            continue

        # 检查今天是否已经发过同类型催收
        already_sent = db.query(ReminderLog).filter(
            ReminderLog.tenant_id == contract.tenant_id,
            ReminderLog.rent_month == month_key,
            ReminderLog.reminder_type == tier,
            ReminderLog.sent_at == target_date,
        ).first()
        if already_sent:
            continue

        text = generate_reminder_text(
            contract.tenant, contract, tier, days_overdue, due_date
        )

        # 记录日志
        log = ReminderLog(
            tenant_id=contract.tenant_id,
            contract_id=contract.id,
            reminder_type=tier,
            rent_month=month_key,
            message_text=text,
            sent_via="log",
        )
        db.add(log)

        reminders[tier].append({
            "tenant": contract.tenant,
            "contract": contract,
            "room": contract.room,
            "text": text,
            "days_overdue": days_overdue,
        })
        reminders["total"] += 1

    if reminders["total"] > 0:
        db.commit()

    return reminders
