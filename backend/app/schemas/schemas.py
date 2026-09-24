"""
Pydantic v2 schemas for request validation and API response serialization.
"""

from __future__ import annotations
from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field

from app.models.inventory import StockStatus
from app.models.order     import OrderStatus, OrderType


# ─────────────────────────────────────────────
# PHC
# ─────────────────────────────────────────────

class PHCBase(BaseModel):
    name:          str
    phc_code:      str
    district:      str
    state:         str           = "Karnataka"
    block:         Optional[str] = None
    village:       Optional[str] = None
    latitude:      float
    longitude:     float
    contact_name:  Optional[str] = None
    contact_phone: Optional[str] = None
    language:      str           = "Kannada"
    is_active:     bool          = True


class PHCCreate(PHCBase):
    pass


class PHCUpdate(BaseModel):
    name:          Optional[str]   = None
    district:      Optional[str]   = None
    block:         Optional[str]   = None
    contact_name:  Optional[str]   = None
    contact_phone: Optional[str]   = None
    language:      Optional[str]   = None
    is_active:     Optional[bool]  = None


class PHCRead(PHCBase):
    model_config = ConfigDict(from_attributes=True)
    id:         int
    created_at: Optional[datetime] = None


# ─────────────────────────────────────────────
# Inventory
# ─────────────────────────────────────────────

class InventoryItemBase(BaseModel):
    phc_id:               int
    nlem_code:            str
    drug_name:            str
    generic_name:         Optional[str]  = None
    dosage_form:          Optional[str]  = None
    strength:             Optional[str]  = None
    unit:                 str            = "tablets"
    batch_no:             Optional[str]  = None
    quantity_on_hand:     int            = 0
    expiry_date:          Optional[date] = None
    avg_daily_consumption: float         = 0.0
    supplier_lead_days:   int            = 7
    safety_stock_days:    int            = 5
    max_stock_level:      Optional[int]  = None


class InventoryItemCreate(InventoryItemBase):
    pass


class InventoryItemUpdate(BaseModel):
    quantity_on_hand:      Optional[int]   = None
    batch_no:              Optional[str]   = None
    expiry_date:           Optional[date]  = None
    avg_daily_consumption: Optional[float] = None
    supplier_lead_days:    Optional[int]   = None
    safety_stock_days:     Optional[int]   = None
    max_stock_level:       Optional[int]   = None


class InventoryItemRead(InventoryItemBase):
    model_config = ConfigDict(from_attributes=True)
    id:            int
    reorder_point: float
    stock_status:  StockStatus
    last_updated:  Optional[datetime] = None


class StockAlertRead(BaseModel):
    """Lightweight alert emitted by the demand engine."""
    model_config = ConfigDict(from_attributes=True)
    inventory_item_id: int
    phc_id:            int
    phc_name:          str
    nlem_code:         str
    drug_name:         str
    quantity_on_hand:  int
    reorder_point:     float
    stock_status:      StockStatus
    days_of_stock_remaining: Optional[float] = None
    expiry_date:       Optional[date]        = None


# ─────────────────────────────────────────────
# Vendor
# ─────────────────────────────────────────────

class VendorBase(BaseModel):
    name:              str
    vendor_code:       str
    district:          str
    state:             str           = "Karnataka"
    contact_name:      Optional[str] = None
    phone:             Optional[str] = None
    whatsapp:          Optional[str] = None
    email:             Optional[str] = None
    preferred_lang:    str           = "Kannada"
    avg_lead_days:     int           = 7
    service_radius_km: Optional[float] = None
    is_active:         bool          = True
    notes:             Optional[str] = None


class VendorCreate(VendorBase):
    pass


class VendorUpdate(BaseModel):
    contact_name:      Optional[str]   = None
    phone:             Optional[str]   = None
    whatsapp:          Optional[str]   = None
    avg_lead_days:     Optional[int]   = None
    preferred_lang:    Optional[str]   = None
    is_active:         Optional[bool]  = None
    notes:             Optional[str]   = None


class VendorRead(VendorBase):
    model_config = ConfigDict(from_attributes=True)
    id:         int
    created_at: Optional[datetime] = None


# ─────────────────────────────────────────────
# Order
# ─────────────────────────────────────────────

class OrderBase(BaseModel):
    phc_id:                int
    vendor_id:             Optional[int]  = None
    source_phc_id:         Optional[int]  = None
    order_type:            OrderType      = OrderType.VENDOR_ORDER
    nlem_code:             str
    drug_name:             str
    quantity_ordered:      int
    expected_delivery_date: Optional[date] = None


class OrderCreate(OrderBase):
    pass


class OrderStatusUpdate(BaseModel):
    status:             OrderStatus
    quantity_delivered: Optional[int]  = None
    actual_delivery_date: Optional[date] = None


class OrderRead(OrderBase):
    model_config = ConfigDict(from_attributes=True)
    id:                    int
    status:                OrderStatus
    quantity_delivered:    Optional[int]  = None
    actual_delivery_date:  Optional[date] = None
    distance_km:           Optional[float] = None
    is_auto_generated:     bool
    sms_sent:              bool
    created_at:            Optional[datetime] = None
    updated_at:            Optional[datetime] = None


# ─────────────────────────────────────────────
# Inter-PHC Transfer suggestion
# ─────────────────────────────────────────────

class TransferSuggestion(BaseModel):
    source_phc_id:   int
    source_phc_name: str
    target_phc_id:   int
    target_phc_name: str
    nlem_code:       str
    drug_name:       str
    suggested_qty:   int
    distance_km:     float


# ─────────────────────────────────────────────
# Generic wrappers
# ─────────────────────────────────────────────

class MessageResponse(BaseModel):
    message: str
    detail:  Optional[str] = None
