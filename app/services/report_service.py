"""报表与统计服务"""
from datetime import date, timedelta
from calendar import monthrange
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models import Tenant, Room, Contract, Payment


def current_month_key() -> str:
    """当前月份键：'2026-07'"""
    today = date.today()
    return f"{today.year}-{today.month:02d}"


def get_dashboard_stats(db: Session) -> dict:
    """仪表盘首页统计数据"""
    today = date.today()
    month_key = current_month_key()

    total_rooms = db.query(func.count(Room.id)).filter(Room.is_active == True).scalar() or 0
    active_contracts = db.query(func.count(Contract.id)).filter(Contract.is_active == True).scalar() or 0
    total_tenants = db.query(func.count(Tenant.id)).filter(Tenant.is_active == True).scalar() or 0

    # 当月应收总额
    expected_rent = db.query(func.sum(Contract.monthly_rent)).filter(
        Contract.is_active == True
    ).scalar() or 0

    # 当月已收总额
    collected = db.query(func.sum(Payment.amount)).filter(
        Payment.rent_month == month_key
    ).scalar() or 0

    # 当月已收户数
    paid_count = db.query(func.count(Payment.id)).filter(
        Payment.rent_month == month_key
    ).scalar() or 0

    # 当月逾期户数（有付款但是逾期的）
    overdue_count = db.query(func.count(Payment.id)).filter(
        Payment.rent_month == month_key,
        Payment.is_arrears == True
    ).scalar() or 0

    # 未缴户数（合同有效但无本月付款记录）
    paid_tenant_ids = set(
        p[0] for p in db.query(Payment.tenant_id).filter(
            Payment.rent_month == month_key
        ).all()
    )
    all_active_tenant_ids = set(
        c[0] for c in db.query(Contract.tenant_id).filter(
            Contract.is_active == True
        ).all()
    )
    unpaid_count = len(all_active_tenant_ids - paid_tenant_ids)

    # 收缴率
    total_due = active_contracts
    collection_rate = round(paid_count / total_due * 100, 1) if total_due > 0 else 0

    # 各楼层收缴情况
    floor_stats = []
    for floor_num in range(1, 12):
        floor_rooms = db.query(Room).filter(Room.floor == floor_num, Room.is_active == True).all()
        if not floor_rooms:
            continue
        room_ids = [r.id for r in floor_rooms]
        floor_contracts = db.query(Contract).filter(
            Contract.room_id.in_(room_ids),
            Contract.is_active == True
        ).all()
        floor_tenant_ids = [c.tenant_id for c in floor_contracts]
        floor_paid = db.query(func.count(Payment.id)).filter(
            Payment.tenant_id.in_(floor_tenant_ids),
            Payment.rent_month == month_key
        ).scalar() or 0
        floor_total = len(floor_contracts)
        floor_rate = round(floor_paid / floor_total * 100, 1) if floor_total > 0 else 0
        floor_stats.append({
            "floor": floor_num,
            "rooms": len(floor_rooms),
            "occupied": floor_total,
            "paid": floor_paid,
            "rate": floor_rate,
        })

    # 最近缴费记录
    recent_payments = db.query(Payment).order_by(
        Payment.created_at.desc()
    ).limit(10).all()

    # 月度收缴趋势（近12个月）
    monthly_trend = []
    for i in range(11, -1, -1):
        d = date.today().replace(day=1) - timedelta(days=1)
        d = d.replace(day=1) - timedelta(days=1) * (11 - i)
        mk = f"{d.year}-{d.month:02d}"
        contracts_count = db.query(func.count(Contract.id)).filter(
            Contract.contract_start_date <= d.replace(day=monthrange(d.year, d.month)[1]),
            Contract.contract_end_date >= d,
            Contract.is_active == True
        ).scalar() or (
            db.query(func.count(Contract.id)).filter(Contract.is_active == True).scalar() or 0
        )
        paid = db.query(func.count(Payment.id)).filter(Payment.rent_month == mk).scalar() or 0
        monthly_trend.append({
            "month": mk,
            "total": contracts_count,
            "paid": paid,
        })

    return {
        "total_rooms": total_rooms,
        "total_tenants": total_tenants,
        "active_contracts": active_contracts,
        "expected_rent": expected_rent,
        "collected": collected,
        "paid_count": paid_count,
        "overdue_count": overdue_count,
        "unpaid_count": unpaid_count,
        "collection_rate": collection_rate,
        "floor_stats": floor_stats,
        "recent_payments": recent_payments,
        "monthly_trend": monthly_trend,
        "month_key": month_key,
    }
