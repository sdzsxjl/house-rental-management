"""银行流水对账路由"""
import shutil
import json
from datetime import datetime, date
from pathlib import Path
from fastapi import APIRouter, Request, Form, UploadFile, File, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from fastapi.templating import Jinja2Templates
from app.database import get_db
from app.models import BankStatement, BankStatementItem, Payment, Contract
from app.routers.auth import get_current_user
from app.config import settings
from app.services.reconciliation import parse_bank_csv, match_transactions

router = APIRouter(prefix="/bank", tags=["银行对账"])
templates = Jinja2Templates(directory="app/templates")


def check_auth(request: Request):
    if not get_current_user(request):
        return RedirectResponse("/login", status_code=303)
    return None


@router.get("")
async def bank_list(request: Request):
    """银行流水列表"""
    if r := check_auth(request): return r
    db: Session = next(get_db())

    statements = db.query(BankStatement).order_by(BankStatement.uploaded_at.desc()).all()

    return templates.TemplateResponse("bank/list.html", {
        "request": request,
        "active_page": "bank",
        "statements": statements,
    })


@router.post("/upload")
async def upload_statement(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """上传银行流水文件"""
    if r := check_auth(request): return r

    # 保存文件
    ext = Path(file.filename).suffix if file.filename else ".csv"
    save_path = settings.UPLOAD_DIR / f"bank_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # 解析文件
    try:
        transactions, bank_name = parse_bank_csv(str(save_path))
    except Exception as e:
        return templates.TemplateResponse("bank/list.html", {
            "request": request,
            "active_page": "bank",
            "error": f"文件解析失败: {str(e)}",
            "statements": db.query(BankStatement).order_by(BankStatement.uploaded_at.desc()).all(),
        })

    # 存储到数据库
    stmt = BankStatement(
        file_name=file.filename,
        bank_name=bank_name,
        uploaded_at=date.today(),
    )
    db.add(stmt)
    db.flush()

    # 匹配交易
    match_results = match_transactions(db, transactions)

    # 存储明细
    item_ids = []
    for txn in match_results:
        item = BankStatementItem(
            bank_statement_id=stmt.id,
            transaction_date=txn["date"],
            amount=txn["amount"],
            direction=txn["direction"],
            counterparty_name=txn["counterparty"],
            counterparty_account=txn.get("counterparty_account", ""),
            summary=txn.get("summary", ""),
            raw_row_json=json.dumps(txn["raw"], ensure_ascii=False),
            matched_tenant_id=txn["match"].id if txn["match"] else None,
            match_confidence=txn["confidence"],
            match_method=txn["method"],
        )
        db.add(item)
        db.flush()
        item_ids.append(item.id)

    db.commit()

    return RedirectResponse(f"/bank/{stmt.id}/review", status_code=303)


@router.get("/{statement_id}/review")
async def review_statement(request: Request, statement_id: int):
    """审核银行流水匹配结果"""
    if r := check_auth(request): return r
    db: Session = next(get_db())

    stmt = db.query(BankStatement).filter(BankStatement.id == statement_id).first()
    if not stmt:
        return RedirectResponse("/bank", status_code=303)

    items = db.query(BankStatementItem).filter(
        BankStatementItem.bank_statement_id == statement_id
    ).order_by(BankStatementItem.match_confidence.desc()).all()

    # 按置信度分组
    high_conf = [i for i in items if i.match_confidence >= 0.85]
    medium_conf = [i for i in items if 0.4 <= i.match_confidence < 0.85]
    low_conf = [i for i in items if i.match_confidence < 0.4]
    unreconciled = [i for i in items if not i.is_reconciled and i.matched_tenant_id]

    return templates.TemplateResponse("bank/review.html", {
        "request": request,
        "active_page": "bank",
        "statement": stmt,
        "high_conf": high_conf,
        "medium_conf": medium_conf,
        "low_conf": low_conf,
        "unreconciled_count": len(unreconciled),
        "total_items": len(items),
    })


@router.post("/confirm")
async def confirm_matches(
    request: Request,
    statement_id: int = Form(...),
    confirm_ids: str = Form(...),  # 逗号分隔的 item ids
    db: Session = Depends(get_db),
):
    """确认匹配 → 自动创建缴费记录"""
    if r := check_auth(request): return r

    ids = [int(i) for i in confirm_ids.split(",") if i.strip()]
    today = date.today()

    for item_id in ids:
        item = db.query(BankStatementItem).filter(BankStatementItem.id == item_id).first()
        if not item or item.is_reconciled:
            continue

        # 获取租客合同
        contract = db.query(Contract).filter(
            Contract.tenant_id == item.matched_tenant_id,
            Contract.is_active == True,
        ).first()
        if not contract:
            continue

        # 确定缴费月份
        pay_date = item.transaction_date
        rent_month = f"{pay_date.year}-{pay_date.month:02d}"

        # 检查是否已有该月记录
        existing = db.query(Payment).filter(
            Payment.tenant_id == item.matched_tenant_id,
            Payment.rent_month == rent_month,
        ).first()
        if existing:
            continue

        # 计算逾期
        due_day = min(contract.payment_due_day, 28)
        rm_year, rm_month = int(rent_month[:4]), int(rent_month[5:7])
        from datetime import date as date_cls
        due_date = date_cls(rm_year, rm_month, due_day)
        is_arrears = pay_date > due_date
        days_late = (pay_date - due_date).days if is_arrears else 0

        payment = Payment(
            tenant_id=item.matched_tenant_id,
            contract_id=contract.id,
            amount=item.amount,
            rent_month=rent_month,
            payment_date=pay_date,
            payment_method="bank_transfer",
            is_arrears=is_arrears,
            days_late=days_late,
            notes=f"银行对账自动匹配 (置信度: {item.match_confidence:.0%})",
            bank_statement_item_id=item.id,
        )
        db.add(payment)

        item.is_reconciled = True
        item.reconciled_at = today

    db.commit()

    return RedirectResponse(f"/bank/{statement_id}/review", status_code=303)
