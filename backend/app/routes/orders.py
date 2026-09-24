"""
Order Routes
POST   /orders                        — create an order (manual or auto)
GET    /orders                        — list orders (filterable by phc/status/type)
GET    /orders/{order_id}             — get single order
PATCH  /orders/{order_id}/status      — advance pipeline status
DELETE /orders/{order_id}             — cancel / delete an order
GET    /orders/pipeline/summary       — count of orders per status (for Kanban)
POST   /orders/auto-generate/{phc_id} — demand engine auto-creates reorders for a PHC
"""

from typing import List, Optional
from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database     import get_db
from app.core.demand_engine import run_reorder_scan
from app.models.order       import Order, OrderStatus, OrderType
from app.models.inventory   import InventoryItem, StockStatus
from app.models.vendor      import Vendor
from app.models.phc         import PHC
from app.schemas.schemas    import (
    OrderCreate, OrderStatusUpdate, OrderRead,
    MessageResponse,
)

router = APIRouter(prefix="/orders", tags=["Orders"])


def _get_order_or_404(order_id: int, db: Session) -> Order:
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    return order


# NOTE: /pipeline/summary must be before /{order_id} to avoid routing clash
@router.get("/pipeline/summary")
def pipeline_summary(
    phc_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(Order)
    if phc_id:
        q = q.filter(Order.phc_id == phc_id)

    result = {}
    for status in OrderStatus:
        result[status.value] = q.filter(Order.status == status).count()
    return result


@router.post("/auto-generate/{phc_id}", response_model=List[OrderRead], status_code=201)
def auto_generate_orders(phc_id: int, db: Session = Depends(get_db)):
    phc = db.query(PHC).filter(PHC.id == phc_id).first()
    if not phc:
        raise HTTPException(status_code=404, detail="PHC not found.")

    alerts = run_reorder_scan(db, phc_id)
    if not alerts:
        return []

    vendor = db.query(Vendor).filter(
        Vendor.district == phc.district,
        Vendor.is_active == True,
    ).order_by(Vendor.avg_lead_days).first()

    open_statuses = [
        OrderStatus.DRAFT,
        OrderStatus.REQUISITION_SENT,
        OrderStatus.VENDOR_CONFIRMED,
        OrderStatus.IN_TRANSIT,
    ]

    new_orders: List[Order] = []
    for alert in alerts:
        existing = db.query(Order).filter(
            Order.phc_id    == phc_id,
            Order.nlem_code == alert.nlem_code,
            Order.status.in_(open_statuses),
        ).first()
        if existing:
            continue

        item = db.query(InventoryItem).filter(
            InventoryItem.id == alert.inventory_item_id
        ).first()
        if not item:
            continue

        thirty_day_supply = int(item.avg_daily_consumption * 30)
        order_qty = max(1, thirty_day_supply - item.quantity_on_hand)

        lead_days = vendor.avg_lead_days if vendor else 7
        exp_delivery = date.today() + timedelta(days=lead_days)

        order = Order(
            phc_id                 = phc_id,
            vendor_id              = vendor.id if vendor else None,
            order_type             = OrderType.VENDOR_ORDER,
            status                 = OrderStatus.DRAFT,
            nlem_code              = alert.nlem_code,
            drug_name              = alert.drug_name,
            quantity_ordered       = order_qty,
            expected_delivery_date = exp_delivery,
            is_auto_generated      = True,
            sms_sent               = False,
            sms_language           = phc.language,
        )
        db.add(order)
        new_orders.append(order)

    db.commit()
    for o in new_orders:
        db.refresh(o)
    return new_orders


@router.get("", response_model=List[OrderRead])
def list_orders(
    phc_id:     Optional[int] = Query(None),
    vendor_id:  Optional[int] = Query(None),
    status:     Optional[str] = Query(None),
    order_type: Optional[str] = Query(None),
    skip:  int = Query(0,   ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(Order)
    if phc_id:
        q = q.filter(Order.phc_id == phc_id)
    if vendor_id:
        q = q.filter(Order.vendor_id == vendor_id)
    if status:
        q = q.filter(Order.status == status)
    if order_type:
        q = q.filter(Order.order_type == order_type)
    return q.order_by(Order.created_at.desc()).offset(skip).limit(limit).all()


@router.post("", response_model=OrderRead, status_code=201)
def create_order(payload: OrderCreate, db: Session = Depends(get_db)):
    if not db.query(PHC).filter(PHC.id == payload.phc_id).first():
        raise HTTPException(status_code=404, detail="PHC not found.")
    if payload.vendor_id and not db.query(Vendor).filter(Vendor.id == payload.vendor_id).first():
        raise HTTPException(status_code=404, detail="Vendor not found.")

    order = Order(**payload.model_dump(), is_auto_generated=False)
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


@router.get("/{order_id}", response_model=OrderRead)
def get_order(order_id: int, db: Session = Depends(get_db)):
    return _get_order_or_404(order_id, db)


_VALID_TRANSITIONS = {
    OrderStatus.DRAFT:            [OrderStatus.REQUISITION_SENT, OrderStatus.CANCELLED],
    OrderStatus.REQUISITION_SENT: [OrderStatus.VENDOR_CONFIRMED, OrderStatus.CANCELLED],
    OrderStatus.VENDOR_CONFIRMED: [OrderStatus.IN_TRANSIT,       OrderStatus.CANCELLED],
    OrderStatus.IN_TRANSIT:       [OrderStatus.DELIVERED,        OrderStatus.CANCELLED],
    OrderStatus.DELIVERED:        [OrderStatus.VERIFIED],
    OrderStatus.VERIFIED:         [],
    OrderStatus.CANCELLED:        [],
}

@router.patch("/{order_id}/status", response_model=OrderRead)
def update_order_status(
    order_id: int,
    payload: OrderStatusUpdate,
    db: Session = Depends(get_db),
):
    order = _get_order_or_404(order_id, db)

    allowed = _VALID_TRANSITIONS.get(order.status, [])
    if payload.status not in allowed:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Cannot move order from '{order.status}' to '{payload.status}'. "
                f"Allowed transitions: {[s.value for s in allowed]}"
            ),
        )

    order.status = payload.status

    if payload.quantity_delivered is not None:
        order.quantity_delivered = payload.quantity_delivered

    if payload.actual_delivery_date is not None:
        order.actual_delivery_date = payload.actual_delivery_date

    if payload.status == OrderStatus.DELIVERED:
        item = db.query(InventoryItem).filter(
            InventoryItem.phc_id    == order.phc_id,
            InventoryItem.nlem_code == order.nlem_code,
        ).first()
        if item and payload.quantity_delivered:
            item.quantity_on_hand += payload.quantity_delivered

    db.commit()
    db.refresh(order)
    return order


@router.delete("/{order_id}", response_model=MessageResponse)
def delete_order(order_id: int, db: Session = Depends(get_db)):
    order = _get_order_or_404(order_id, db)
    if order.status not in (OrderStatus.DRAFT, OrderStatus.CANCELLED):
        raise HTTPException(
            status_code=422,
            detail="Only DRAFT or CANCELLED orders can be deleted. Cancel the order first.",
        )
    db.delete(order)
    db.commit()
    return MessageResponse(message=f"Order {order_id} deleted.")
