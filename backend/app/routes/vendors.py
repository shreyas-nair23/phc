"""
Vendor Routes
GET    /vendors               — list all vendors (filterable by district)
POST   /vendors               — create a vendor
GET    /vendors/{vendor_id}   — get single vendor
PATCH  /vendors/{vendor_id}   — update vendor details
GET    /vendors/{vendor_id}/orders — list orders assigned to this vendor
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database  import get_db
from app.models.vendor  import Vendor
from app.models.order   import Order
from app.schemas.schemas import (
    VendorCreate, VendorUpdate, VendorRead,
    OrderRead,
    MessageResponse,
)

router = APIRouter(prefix="/vendors", tags=["Vendors"])


@router.get("", response_model=List[VendorRead])
def list_vendors(
    district: Optional[str] = Query(None),
    active:   Optional[bool] = Query(None),
    skip:  int = Query(0,   ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(Vendor)
    if district:
        q = q.filter(Vendor.district.ilike(f"%{district}%"))
    if active is not None:
        q = q.filter(Vendor.is_active == active)
    return q.offset(skip).limit(limit).all()


@router.post("", response_model=VendorRead, status_code=201)
def create_vendor(payload: VendorCreate, db: Session = Depends(get_db)):
    if db.query(Vendor).filter(Vendor.vendor_code == payload.vendor_code).first():
        raise HTTPException(status_code=409, detail=f"Vendor code '{payload.vendor_code}' already exists.")
    vendor = Vendor(**payload.model_dump())
    db.add(vendor)
    db.commit()
    db.refresh(vendor)
    return vendor


@router.get("/{vendor_id}", response_model=VendorRead)
def get_vendor(vendor_id: int, db: Session = Depends(get_db)):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found.")
    return vendor


@router.patch("/{vendor_id}", response_model=VendorRead)
def update_vendor(vendor_id: int, payload: VendorUpdate, db: Session = Depends(get_db)):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(vendor, field, value)
    db.commit()
    db.refresh(vendor)
    return vendor


@router.get("/{vendor_id}/orders", response_model=List[OrderRead])
def get_vendor_orders(
    vendor_id: int,
    status: Optional[str] = Query(None),
    skip:  int = Query(0,  ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    if not db.query(Vendor).filter(Vendor.id == vendor_id).first():
        raise HTTPException(status_code=404, detail="Vendor not found.")
    q = db.query(Order).filter(Order.vendor_id == vendor_id)
    if status:
        q = q.filter(Order.status == status)
    return q.order_by(Order.created_at.desc()).offset(skip).limit(limit).all()
