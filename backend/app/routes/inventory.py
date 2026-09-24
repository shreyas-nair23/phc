"""
Inventory Routes
POST   /inventory                     — add a new inventory item to a PHC
GET    /inventory/{item_id}           — get single item
PATCH  /inventory/{item_id}           — update stock quantity / batch / expiry
DELETE /inventory/{item_id}           — remove item
GET    /inventory/network/alerts      — run demand scan across ALL PHCs
POST   /inventory/network/refresh-rop — bulk recompute reorder_points
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database     import get_db
from app.core.demand_engine import (
    compute_reorder_point,
    classify_stock_status,
    run_network_reorder_scan,
    refresh_all_reorder_points,
)
from app.models.inventory  import InventoryItem
from app.models.phc        import PHC
from app.schemas.schemas   import (
    InventoryItemCreate,
    InventoryItemUpdate,
    InventoryItemRead,
    StockAlertRead,
    MessageResponse,
)

router = APIRouter(prefix="/inventory", tags=["Inventory"])


@router.post("", response_model=InventoryItemRead, status_code=201)
def create_inventory_item(payload: InventoryItemCreate, db: Session = Depends(get_db)):
    if not db.query(PHC).filter(PHC.id == payload.phc_id).first():
        raise HTTPException(status_code=404, detail="PHC not found.")

    rop = compute_reorder_point(
        payload.avg_daily_consumption,
        payload.supplier_lead_days,
        payload.safety_stock_days,
    )
    status = classify_stock_status(
        quantity_on_hand=payload.quantity_on_hand,
        reorder_point=rop,
        avg_daily_consumption=payload.avg_daily_consumption,
        expiry_date=payload.expiry_date,
    )

    item = InventoryItem(
        **payload.model_dump(),
        reorder_point=rop,
        stock_status=status,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


# NOTE: /network/alerts must be defined BEFORE /{item_id} to avoid routing clash
@router.get("/network/alerts", response_model=List[StockAlertRead])
def get_network_alerts(db: Session = Depends(get_db)):
    return run_network_reorder_scan(db)


@router.post("/network/refresh-rop", response_model=MessageResponse)
def refresh_reorder_points(db: Session = Depends(get_db)):
    count = refresh_all_reorder_points(db)
    return MessageResponse(message=f"Reorder points refreshed for {count} inventory items.")


@router.get("/{item_id}", response_model=InventoryItemRead)
def get_inventory_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(InventoryItem).filter(InventoryItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found.")
    return item


@router.patch("/{item_id}", response_model=InventoryItemRead)
def update_inventory_item(
    item_id: int,
    payload: InventoryItemUpdate,
    db: Session = Depends(get_db),
):
    item = db.query(InventoryItem).filter(InventoryItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found.")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)

    item.reorder_point = compute_reorder_point(
        item.avg_daily_consumption,
        item.supplier_lead_days,
        item.safety_stock_days,
    )
    item.stock_status = classify_stock_status(
        quantity_on_hand=item.quantity_on_hand,
        reorder_point=item.reorder_point,
        avg_daily_consumption=item.avg_daily_consumption,
        expiry_date=item.expiry_date,
    )

    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", response_model=MessageResponse)
def delete_inventory_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(InventoryItem).filter(InventoryItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found.")
    db.delete(item)
    db.commit()
    return MessageResponse(message="Inventory item deleted successfully.")
