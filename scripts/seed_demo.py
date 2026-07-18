"""生成演示数据（写入独立的 demo.db，不影响真实数据）

用法：
    python scripts/seed_demo.py

生成后会提示如何用演示数据启动系统。
所有数据均为虚构，仅用于演示 / 截图 / 测试。
"""
import os
import sys
from pathlib import Path
from datetime import date, datetime

# 固定写入独立的 demo.db，避免污染真实数据
BASE_DIR = Path(__file__).resolve().parent.parent
DEMO_DB = BASE_DIR / "data" / "demo.db"
sys.path.insert(0, str(BASE_DIR))
os.environ["DATABASE_URL"] = f"sqlite:///{DEMO_DB}"
os.environ.setdefault("ADMIN_PASSWORD", "admin123")

# 在设置好环境变量后再导入应用模块
from app.database import engine, Base, SessionLocal
import app.models  # noqa: F401  确保所有模型已注册
from app.models import (
    Room, Tenant, Contract, Payment, UtilityBill, BankStatement, BankStatementItem,
    ReminderLog,
)

WATER_UNIT_PRICE = 6.0
ELEC_UNIT_PRICE = 1.0


def reset_and_seed() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # ─── 房间（3 层 5 间 + 5 层 3 间）────────────────────────
    rooms = []
    for floor, nums in [(3, ["501", "502", "503", "504", "505"]),
                        (5, ["501", "502", "503"])]:
        for num in nums:
            r = Room(floor=floor, room_number=num, area_sqm=25.0, layout="单间")
            db.add(r)
            rooms.append(r)

    # ─── 租客（姓名 / 手机号均为虚构）────────────────────────
    tenant_data = [
        ("张伟", "13800000001", "zhangwei_wx"),
        ("李娜", "13800000002", "lina_wx"),
        ("王强", "13800000003", "wangqiang_wx"),
        ("刘洋", "13800000004", "liuyang_wx"),
        ("陈静", "13800000005", "chenjing_wx"),
        ("杨帆", "13800000006", "yangfan_wx"),
        ("赵敏", "13800000007", "zhaomin_wx"),
        ("黄磊", "13800000008", "huanglei_wx"),
    ]
    tenants = []
    for name, phone, wx in tenant_data:
        t = Tenant(name=name, phone=phone, wechat_id=wx)
        db.add(t)
        tenants.append(t)

    # ─── 合同 ────────────────────────────────────────────────
    rents = [2200, 2600, 1850, 3000, 2400, 2100, 2750, 1950]
    due_days = [1, 5, 12, 18, 8, 19, 21, 23]
    contracts = []
    for i, (tenant, room) in enumerate(zip(tenants, rooms)):
        c = Contract(
            tenant=tenant, room=room,
            monthly_rent=rents[i], deposit=rents[i],
            payment_due_day=due_days[i],
            contract_start_date=date(2025, 7, 1),
            contract_end_date=date(2026, 12, 31),
            is_active=True,
        )
        db.add(c)
        contracts.append(c)
    db.flush()

    # ─── 缴费记录（近 3 个月，当月部分未缴）──────────────────
    for month in ["2026-07", "2026-08"]:
        for i, c in enumerate(contracts):
            db.add(Payment(
                tenant=c.tenant, contract=c,
                amount=c.monthly_rent, rent_month=month,
                payment_date=date(int(month[:4]), int(month[5:7]), 3),
                payment_method=["wechat", "alipay", "bank_transfer", "cash"][i % 4],
            ))
    # 2026-09（当月）：前 3 户已缴（张伟逾期 1 天），后 5 户未缴 → 催租面板三档齐全
    pay_dates = [date(2026, 9, 2), date(2026, 9, 3), date(2026, 9, 8)]
    for i, c in enumerate(contracts[:3]):
        db.add(Payment(
            tenant=c.tenant, contract=c,
            amount=c.monthly_rent, rent_month="2026-09",
            payment_date=pay_dates[i],
            payment_method="wechat" if i != 2 else "bank_transfer",
            is_arrears=(i == 0), days_late=(1 if i == 0 else 0),
        ))

    # ─── 催租历史（模拟已推送的记录，供催租面板展示）──────────
    reminder_history = [
        (3, "overdue", "2026-09-18", "sms", "【严重逾期警告】刘洋您好，您9月的租金 ¥3000 已逾期 5 天，请于 3 日内结清。"),
        (4, "overdue", "2026-09-20", "log", "【最后催缴】陈静，9月房租 ¥2400 已严重逾期 15 天，请立即缴纳。"),
        (5, "warning", "2026-09-21", "wechat", "【催缴通知】杨帆您好，9月租金 ¥2100 已超过缴费日 4 天，请尽快安排支付。"),
        (6, "gentle", "2026-09-22", "log", "【交租提醒】赵敏，9月份的房租 ¥2750 今天可以交了哦～"),
    ]
    for idx, tier, sent, via, text in reminder_history:
        db.add(ReminderLog(
            tenant_id=tenants[idx].id, contract_id=contracts[idx].id,
            reminder_type=tier, rent_month="2026-09",
            message_text=text, sent_via=via, sent_at=date.fromisoformat(sent),
        ))

    # ─── 水电账单（2026-09，前 5 间已出账）────────────────────
    readings = [
        (100.0, 103.0, 620.0, 850.0),
        (85.0, 89.0, 500.0, 740.0),
        (112.0, 114.0, 700.0, 920.0),
        (95.0, 101.0, 540.0, 810.0),
        (120.0, 123.0, 660.0, 900.0),
    ]
    for i, (room, c) in enumerate(zip(rooms[:5], contracts[:5])):
        w_prev, w_cur, e_prev, e_cur = readings[i]
        w_usage = w_cur - w_prev
        e_usage = e_cur - e_prev
        w_fee = round(w_usage * WATER_UNIT_PRICE, 2)
        e_fee = round(e_usage * ELEC_UNIT_PRICE, 2)
        db.add(UtilityBill(
            room=room, bill_month="2026-09",
            water_previous_reading=w_prev, water_current_reading=w_cur,
            water_usage=w_usage, water_unit_price=WATER_UNIT_PRICE, water_fee=w_fee,
            electricity_previous_reading=e_prev, electricity_current_reading=e_cur,
            electricity_usage=e_usage, electricity_unit_price=ELEC_UNIT_PRICE, electricity_fee=e_fee,
            monthly_rent=c.monthly_rent,
            total_amount=round(w_fee + e_fee + c.monthly_rent, 2),
            status="calculated",
        ))

    # ─── 银行流水 + 智能匹配结果 ─────────────────────────────
    stmt = BankStatement(
        file_name="建设银行流水_2026-08.csv", bank_name="CCB",
        statement_period_start=date(2026, 8, 1), statement_period_end=date(2026, 8, 31),
        uploaded_at=date(2026, 9, 1),
    )
    db.add(stmt)
    db.flush()

    bank_items = [
        # (金额, 方向, 对方户名, 摘要, 匹配租客索引, 置信度, 方法, 已对账)
        (2200.0, "credit", "张伟", "转账", 0, 0.95, "amount_exact", False),
        (2600.0, "credit", "李娜", "转账", 1, 0.95, "amount_exact", True),
        (1850.0, "credit", "王强", "转账", 2, 0.88, "amount_fuzzy", False),
        (3000.0, "credit", "刘洋", "工资转入", 3, 0.92, "ai", False),
        (5000.0, "credit", "未知账户", "转账", None, 0.0, "", False),
        (320.0, "debit", "物业公司", "物业费", None, 0.0, "", False),
    ]
    for amount, direction, cpty, summary, t_idx, conf, method, reconciled in bank_items:
        db.add(BankStatementItem(
            statement=stmt, transaction_date=date(2026, 8, 15),
            amount=amount, direction=direction,
            counterparty_name=cpty, counterparty_account="", summary=summary,
            matched_tenant=(tenants[t_idx] if t_idx is not None else None),
            match_confidence=conf, match_method=method,
            is_reconciled=reconciled,
            reconciled_at=(date(2026, 8, 20) if reconciled else None),
        ))

    db.commit()
    db.close()

    print("[OK] 演示数据已生成:", DEMO_DB)
    print()
    print("用演示数据启动系统：")
    print("  set DATABASE_URL=sqlite:///./data/demo.db   (Windows CMD)")
    print("  python run.py")
    print()
    print("默认登录账号：admin / admin123")


if __name__ == "__main__":
    reset_and_seed()
