"""缴费记录模型"""
from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, Float, Boolean, Date, String, Text, ForeignKey, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from app.database import Base


class Payment(Base):
    """缴费记录"""
    __tablename__ = "payment"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenant.id"), nullable=False)
    contract_id = Column(Integer, ForeignKey("contract.id"), nullable=False)
    amount = Column(Float, nullable=False)
    rent_month = Column(String(7), nullable=False)  # "2026-07"
    payment_date = Column(Date, nullable=False, default=date.today)
    payment_method = Column(String(20), default="manual")  # wechat/alipay/bank_transfer/cash/manual
    is_arrears = Column(Boolean, default=False)
    days_late = Column(Integer, default=0)
    notes = Column(Text)
    bank_statement_item_id = Column(Integer, ForeignKey("bank_statement_item.id"), nullable=True)
    created_at = Column(Date, default=datetime.now)

    tenant = relationship("Tenant", back_populates="payments")
    contract = relationship("Contract", back_populates="payments")
    bank_statement_item = relationship("BankStatementItem", back_populates="payment")

    __table_args__ = (
        UniqueConstraint("tenant_id", "rent_month", name="uq_payment_tenant_month"),
    )

    def __repr__(self):
        return f"<Payment {self.tenant.name} {self.rent_month} ¥{self.amount}>"
