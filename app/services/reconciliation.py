"""银行流水解析与智能匹配"""
import json
import pandas as pd
from datetime import date
from typing import Optional
from pathlib import Path
from sqlalchemy.orm import Session
from app.models import Tenant, Contract, BankStatement, BankStatementItem
from app.config import settings


# ─── 银行列名映射 ───────────────────────────────────────────

BANK_MAPPINGS = {
    "CCB": {
        "transaction_date": ["交易日期", "记账日期", "发生日期"],
        "amount_credit": ["收入金额", "存入金额", "贷方金额"],
        "amount_debit": ["支出金额", "取款金额", "借方金额"],
        "counterparty": ["对方户名", "对方单位名称", "交易对方"],
        "counterparty_account": ["对方账号", "对方账户"],
        "summary": ["摘要", "用途", "附言", "备注"],
    },
    "ICBC": {
        "transaction_date": ["交易日期", "记账日期"],
        "amount_credit": ["收入金额", "贷方发生额"],
        "amount_debit": ["支出金额", "借方发生额"],
        "counterparty": ["对方户名", "对方单位"],
        "counterparty_account": ["对方账号"],
        "summary": ["摘要", "用途", "汇款附言"],
    },
}

ENCODINGS_TO_TRY = ["utf-8", "gbk", "gb2312", "gb18030", "utf-8-sig", "utf-16"]


def detect_bank_and_read(file_path: str) -> tuple:
    """
    自动检测银行类型并解析 CSV/Excel 文件
    返回: (bank_name: str, df: pd.DataFrame)
    """
    file_ext = Path(file_path).suffix.lower()

    # 先尝试读取
    if file_ext in (".xlsx", ".xls"):
        df = pd.read_excel(file_path)
    else:
        df = None
        for enc in ENCODINGS_TO_TRY:
            try:
                df = pd.read_csv(file_path, encoding=enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        if df is None:
            raise ValueError("无法解析文件编码，请确保文件为 CSV (UTF-8/GBK) 或 Excel 格式")

    # 检测银行类型
    columns_lower = [str(c).lower().strip() for c in df.columns]
    detected_bank = "UNKNOWN"

    for bank_name, mapping in BANK_MAPPINGS.items():
        matches = 0
        for key, aliases in mapping.items():
            for alias in aliases:
                for col in columns_lower:
                    if alias.lower() in col:
                        matches += 1
                        break
                if matches > 0:
                    break
        if matches >= 3:  # 至少匹配3个关键列
            detected_bank = bank_name
            break

    return detected_bank, df


def map_columns(bank_name: str, df: pd.DataFrame) -> dict:
    """将 DataFrame 列名映射为标准字段"""
    mapping = BANK_MAPPINGS.get(bank_name, {})
    columns_lower = {str(c): c for c in df.columns}

    mapped = {
        "date_col": None,
        "credit_col": None,
        "debit_col": None,
        "counterparty_col": None,
        "counterparty_account_col": None,
        "summary_col": None,
    }

    # 交易日期
    for alias in mapping.get("transaction_date", []):
        for col_lower, col_orig in columns_lower.items():
            if alias.lower() in col_lower:
                mapped["date_col"] = col_orig
                break
        if mapped["date_col"]:
            break

    # 收入金额
    for alias in mapping.get("amount_credit", []):
        for col_lower, col_orig in columns_lower.items():
            if alias.lower() in col_lower:
                mapped["credit_col"] = col_orig
                break
        if mapped["credit_col"]:
            break

    # 支出金额
    for alias in mapping.get("amount_debit", []):
        for col_lower, col_orig in columns_lower.items():
            if alias.lower() in col_lower:
                mapped["debit_col"] = col_orig
                break
        if mapped["debit_col"]:
            break

    # 对方户名
    for alias in mapping.get("counterparty", []):
        for col_lower, col_orig in columns_lower.items():
            if alias.lower() in col_lower:
                mapped["counterparty_col"] = col_orig
                break
        if mapped["counterparty_col"]:
            break

    # 对方账号
    for alias in mapping.get("counterparty_account", []):
        for col_lower, col_orig in columns_lower.items():
            if alias.lower() in col_lower:
                mapped["counterparty_account_col"] = col_orig
                break
        if mapped["counterparty_account_col"]:
            break

    # 摘要
    for alias in mapping.get("summary", []):
        for col_lower, col_orig in columns_lower.items():
            if alias.lower() in col_lower:
                mapped["summary_col"] = col_orig
                break
        if mapped["summary_col"]:
            break

    # 如果没识别到列名映射，尝试智能匹配
    if not mapped["date_col"]:
        # 找"日期"相关列
        for col_lower, col_orig in columns_lower.items():
            if any(kw in col_lower for kw in ["日期", "date", "时间"]):
                mapped["date_col"] = col_orig
                break

    if not mapped["credit_col"] and not mapped["debit_col"]:
        # 找"金额"相关列
        for col_lower, col_orig in columns_lower.items():
            if any(kw in col_lower for kw in ["金额", "amount", "收入", "存入"]):
                mapped["credit_col"] = col_orig
                break

    return mapped


def parse_bank_csv(file_path: str) -> list[dict]:
    """
    解析银行流水文件，返回标准化的交易列表
    返回: [{"date": date, "amount": float, "direction": "credit/debit", "counterparty": "", "summary": "", "raw": {}}]
    """
    bank_name, df = detect_bank_and_read(file_path)
    col_map = map_columns(bank_name, df)

    transactions = []

    for _, row in df.iterrows():
        row_dict = row.to_dict()
        # 处理可空值
        for k in row_dict:
            if pd.isna(row_dict[k]):
                row_dict[k] = None

        # 日期
        txn_date = None
        if col_map["date_col"]:
            raw_date = row_dict.get(col_map["date_col"])
            if raw_date:
                try:
                    txn_date = pd.Timestamp(raw_date).date()
                except Exception:
                    try:
                        txn_date = date.fromisoformat(str(raw_date)[:10])
                    except Exception:
                        continue

        if txn_date is None:
            continue

        # 金额和方向
        amount = 0.0
        direction = "credit"

        if col_map["credit_col"] and row_dict.get(col_map["credit_col"]):
            val = float(row_dict[col_map["credit_col"]])
            if val > 0:
                amount = val
                direction = "credit"

        if col_map["debit_col"] and row_dict.get(col_map["debit_col"]):
            val = float(row_dict[col_map["debit_col"]])
            if val > 0:
                amount = val
                direction = "debit"

        # 如果只有一个金额列（没有收/支区分），正数为收入
        if amount == 0 and col_map["credit_col"] and not col_map["debit_col"]:
            val = row_dict.get(col_map["credit_col"])
            if val:
                val = float(val)
                if val > 0:
                    amount = val
                else:
                    amount = abs(val)
                    direction = "debit"

        if amount <= 0:
            continue

        counterparty = ""
        if col_map["counterparty_col"]:
            counterparty = str(row_dict.get(col_map["counterparty_col"], "")).strip()

        summary = ""
        if col_map["summary_col"]:
            summary = str(row_dict.get(col_map["summary_col"], "")).strip()

        transactions.append({
            "date": txn_date,
            "amount": amount,
            "direction": direction,
            "counterparty": counterparty,
            "counterparty_account": str(row_dict.get(col_map["counterparty_account_col"] or "", "")).strip() if col_map.get("counterparty_account_col") else "",
            "summary": summary,
            "raw": {str(k): str(v) if v is not None else "" for k, v in row_dict.items()},
        })

    return transactions, bank_name


def match_transactions(
    db: Session,
    transactions: list[dict],
) -> list[dict]:
    """
    三遍法智能匹配银行交易到租客
    """
    tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
    contracts = {
        c.tenant_id: c
        for c in db.query(Contract).filter(Contract.is_active == True).all()
    }

    results = []

    for txn in transactions:
        if txn["direction"] != "credit":
            # 只关心收入
            results.append({**txn, "match": None, "confidence": 0, "method": ""})
            continue

        match = None
        confidence = 0.0
        method = ""

        # ── 第一遍：精确金额 + 姓名匹配 ──
        for tenant in tenants:
            contract = contracts.get(tenant.id)
            if not contract:
                continue
            if abs(txn["amount"] - contract.monthly_rent) < 0.01:
                # 金额匹配，检查姓名
                cpty = txn["counterparty"]
                if cpty and tenant.name in cpty:
                    match = tenant
                    confidence = 0.95
                    method = "amount_exact"
                    break
                # 金额匹配但姓名不匹配
                if match is None:
                    match = tenant
                    confidence = 0.70
                    method = "amount_exact"

        # ── 第二遍：金额近似匹配（允许±5元差异）──
        if confidence < 0.70:
            for tenant in tenants:
                contract = contracts.get(tenant.id)
                if not contract:
                    continue
                diff = abs(txn["amount"] - contract.monthly_rent)
                if 0 < diff <= 5:
                    cpty = txn["counterparty"]
                    if cpty and tenant.name in cpty:
                        match = tenant
                        confidence = 0.80
                        method = "amount_fuzzy"
                        break
                    if match is None:
                        match = tenant
                        confidence = 0.55
                        method = "amount_fuzzy"

        # ── 第三遍（可选）：LLM 匹配 ──
        if confidence < 0.80 and settings.llm_enabled:
            ai_match = _ai_match_transaction(txn, tenants, contracts)
            if ai_match and ai_match["confidence"] > confidence:
                match = ai_match["tenant"]
                confidence = ai_match["confidence"]
                method = "ai"

        results.append({
            **txn,
            "match": match,
            "confidence": round(confidence, 2),
            "method": method,
        })

    return results


def _ai_match_transaction(
    txn: dict,
    tenants: list[Tenant],
    contracts: dict,
) -> Optional[dict]:
    """调用 LLM 匹配交易"""
    import json
    from openai import OpenAI

    tenants_info = [
        {
            "id": t.id,
            "name": t.name,
            "phone": t.phone,
            "rent": contracts[t.id].monthly_rent if t.id in contracts else None,
        }
        for t in tenants
    ]

    prompt = f"""你是一个银行流水对账助手。请将以下银行交易匹配到最可能的租客。

银行交易:
- 金额: {txn['amount']}元
- 交易日期: {txn['date']}
- 对方户名: {txn['counterparty']}
- 摘要: {txn['summary']}

租客列表:
{json.dumps(tenants_info, ensure_ascii=False, indent=2)}

请根据金额匹配和姓名匹配判断是哪个租客付的租金。返回JSON格式:
{{"tenant_id": null或数字, "confidence": 0.0到1.0, "reason": "简短的匹配理由"}}
如果无法确定，tenant_id 设为 null，confidence 设为 0。

只返回JSON，不要其他文字。"""

    try:
        client = OpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_API_BASE,
        )
        resp = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.1,
        )
        text = resp.choices[0].message.content.strip()
        # 提取 JSON
        if "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        if text.startswith("json"):
            text = text[4:].strip()
        result = json.loads(text)

        if result.get("tenant_id"):
            tid = result["tenant_id"]
            tenant = next((t for t in tenants if t.id == tid), None)
            return {"tenant": tenant, "confidence": result.get("confidence", 0.5)}
    except Exception:
        pass

    return None
