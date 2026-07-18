"""银行流水模型"""
from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, Float, String, Text, Date, Boolean, ForeignKey,
)
from sqlalchemy.orm import relationship
from app.database import Base


class BankStatement(Base):
    """银行流水文件"""
    __tablename__ = "bank_statement"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_name = Column(String(200), nullable=False)
    bank_name = Column(String(50))  # CCB/ICBC/ABC/BOC
    statement_period_start = Column(Date)
    statement_period_end = Column(Date)
    uploaded_at = Column(Date, default=datetime.now)

    items = relationship("BankStatementItem", back_populates="statement")

    def __repr__(self):
        return f"<BankStatement {self.bank_name} {self.file_name}>"


class BankStatementItem(Base):
    """银行流水明细"""
    __tablename__ = "bank_statement_item"

    id = Column(Integer, primary_key=True, autoincrement=True)
    bank_statement_id = Column(Integer, ForeignKey("bank_statement.id"), nullable=False)
    transaction_date = Column(Date, nullable=False)
    amount = Column(Float, nullable=False)
    direction = Column(String(10), nullable=False)  # credit(收入)/debit(支出)
    counterparty_name = Column(String(100))  # 对方户名
    counterparty_account = Column(String(50))  # 对方账号
    summary = Column(Text)  # 摘要/用途
    raw_row_json = Column(Text)  # 原始 CSV 行 JSON
    matched_tenant_id = Column(Integer, ForeignKey("tenant.id"), nullable=True)
    match_confidence = Column(Float, default=0.0)  # 0.0 ~ 1.0
    match_method = Column(String(20))  # ai/amount_exact/manual
    is_reconciled = Column(Boolean, default=False)
    reconciled_at = Column(Date)

    statement = relationship("BankStatement", back_populates="items")
    matched_tenant = relationship("Tenant")
    payment = relationship("Payment", back_populates="bank_statement_item", uselist=False)

    def __repr__(self):
        return f"<BankItem {self.transaction_date} ¥{self.amount} {self.direction}>"
