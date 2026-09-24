"""
PHC (Primary Health Centre) model.
Stores location, contact, and operational metadata for each centre.
"""

from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class PHC(Base):
    __tablename__ = "phcs"

    id = Column(Integer, primary_key=True, index=True)

    # Identity
    name        = Column(String(200), nullable=False)
    phc_code    = Column(String(50),  unique=True, nullable=False, index=True)
    district    = Column(String(100), nullable=False)
    state       = Column(String(100), nullable=False, default="Karnataka")
    block       = Column(String(100), nullable=True)   # sub-district / taluka
    village     = Column(String(100), nullable=True)

    # Geospatial (WGS-84 decimal degrees)
    latitude    = Column(Float, nullable=False)
    longitude   = Column(Float, nullable=False)

    # Contact
    contact_name  = Column(String(150), nullable=True)
    contact_phone = Column(String(20),  nullable=True)
    language      = Column(String(50),  nullable=False, default="Kannada")

    # Status
    is_active   = Column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    inventory_items = relationship("InventoryItem", back_populates="phc", cascade="all, delete-orphan")
    orders          = relationship("Order",         back_populates="phc", cascade="all, delete-orphan", foreign_keys="Order.phc_id")

    def __repr__(self):
        return f"<PHC id={self.id} code={self.phc_code} name={self.name!r}>"
