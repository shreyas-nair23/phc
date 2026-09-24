"""
Vendor model.
Represents district-level medicine suppliers linked to one or more PHCs.
"""

from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class Vendor(Base):
    __tablename__ = "vendors"

    id = Column(Integer, primary_key=True, index=True)

    # Identity
    name          = Column(String(200), nullable=False)
    vendor_code   = Column(String(50),  unique=True, nullable=False, index=True)
    district      = Column(String(100), nullable=False)
    state         = Column(String(100), nullable=False, default="Karnataka")

    # Contact & comms
    contact_name   = Column(String(150), nullable=True)
    phone          = Column(String(20),  nullable=True)
    whatsapp       = Column(String(20),  nullable=True)
    email          = Column(String(150), nullable=True)
    preferred_lang = Column(String(50),  nullable=False, default="Kannada")

    # Logistics
    avg_lead_days     = Column(Integer, nullable=False, default=7)
    service_radius_km = Column(Float, nullable=True)

    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    notes     = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    orders = relationship("Order", back_populates="vendor")

    def __repr__(self):
        return f"<Vendor id={self.id} code={self.vendor_code} name={self.name!r}>"
