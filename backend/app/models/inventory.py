"""
Inventory model.
Tracks per-PHC medicine stock with batch, expiry, and consumption velocity.
"""

from sqlalchemy import (
    Column, Integer, String, Float, Date,
    DateTime, ForeignKey, Enum as SAEnum
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from app.core.database import Base


class StockStatus(str, enum.Enum):
    HEALTHY   = "healthy"    # above reorder point
    LOW       = "low"        # at or below reorder point
    CRITICAL  = "critical"   # ≤ 3 days of stock remaining
    EXPIRED   = "expired"    # past expiry date
    EXPIRING  = "expiring"   # within 30 days of expiry


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id      = Column(Integer, primary_key=True, index=True)
    phc_id  = Column(Integer, ForeignKey("phcs.id", ondelete="CASCADE"), nullable=False, index=True)

    # Drug identity (aligned to NLEM 2022 codes)
    nlem_code    = Column(String(20),  nullable=False, index=True)
    drug_name    = Column(String(200), nullable=False)
    generic_name = Column(String(200), nullable=True)
    dosage_form  = Column(String(100), nullable=True)
    strength     = Column(String(50),  nullable=True)
    unit         = Column(String(30),  nullable=False, default="tablets")

    # Batch & stock
    batch_no         = Column(String(100), nullable=True)
    quantity_on_hand = Column(Integer,     nullable=False, default=0)
    expiry_date      = Column(Date,        nullable=True)

    # Consumption & reorder parameters
    avg_daily_consumption = Column(Float, nullable=False, default=0.0)
    supplier_lead_days    = Column(Integer, nullable=False, default=7)
    safety_stock_days     = Column(Integer, nullable=False, default=5)
    reorder_point         = Column(Float, nullable=False, default=0.0)
    max_stock_level       = Column(Integer, nullable=True)

    # Computed status (updated by demand engine)
    stock_status = Column(
        SAEnum(StockStatus, name="stock_status_enum"),
        nullable=False,
        default=StockStatus.HEALTHY,
    )

    # Timestamps
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    phc = relationship("PHC", back_populates="inventory_items")

    def __repr__(self):
        return (
            f"<InventoryItem phc_id={self.phc_id} drug={self.drug_name!r} "
            f"qty={self.quantity_on_hand} status={self.stock_status}>"
        )
