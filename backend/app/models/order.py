"""
Order model.
Tracks the full lifecycle of a medicine requisition:
    Requisition Sent → Vendor Confirmed → In Transit → Delivered & Verified
Also supports Inter-PHC peer-to-peer transfer orders.
"""

from sqlalchemy import (
    Column, Integer, String, Float, Date, DateTime,
    ForeignKey, Text, Boolean, Enum as SAEnum
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from app.core.database import Base


class OrderStatus(str, enum.Enum):
    DRAFT               = "draft"
    REQUISITION_SENT    = "requisition_sent"
    VENDOR_CONFIRMED    = "vendor_confirmed"
    IN_TRANSIT          = "in_transit"
    DELIVERED           = "delivered"
    VERIFIED            = "verified"
    CANCELLED           = "cancelled"


class OrderType(str, enum.Enum):
    VENDOR_ORDER   = "vendor_order"
    INTER_PHC      = "inter_phc"


class Order(Base):
    __tablename__ = "orders"

    id        = Column(Integer, primary_key=True, index=True)
    phc_id    = Column(Integer, ForeignKey("phcs.id",    ondelete="CASCADE"), nullable=False, index=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True,  index=True)

    source_phc_id = Column(Integer, ForeignKey("phcs.id", ondelete="SET NULL"), nullable=True)

    order_type = Column(
        SAEnum(OrderType, name="order_type_enum"),
        nullable=False,
        default=OrderType.VENDOR_ORDER,
    )
    status = Column(
        SAEnum(OrderStatus, name="order_status_enum"),
        nullable=False,
        default=OrderStatus.DRAFT,
        index=True,
    )

    nlem_code          = Column(String(20),  nullable=False)
    drug_name          = Column(String(200), nullable=False)
    quantity_ordered   = Column(Integer, nullable=False)
    quantity_delivered = Column(Integer, nullable=True)

    expected_delivery_date = Column(Date, nullable=True)
    actual_delivery_date   = Column(Date, nullable=True)

    distance_km       = Column(Float,   nullable=True)
    is_auto_generated = Column(Boolean, default=False)

    sms_sent     = Column(Boolean, default=False)
    sms_language = Column(String(50), nullable=True)
    sms_message  = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    phc        = relationship("PHC",    back_populates="orders", foreign_keys=[phc_id])
    vendor     = relationship("Vendor", back_populates="orders")
    source_phc = relationship("PHC",    foreign_keys=[source_phc_id])

    def __repr__(self):
        return (
            f"<Order id={self.id} phc_id={self.phc_id} drug={self.drug_name!r} "
            f"status={self.status} type={self.order_type}>"
        )
