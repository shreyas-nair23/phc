"""
Analytics Routes — read-only aggregations for the admin dashboard
GET /analytics/district-summary        — stock health per district
GET /analytics/network-map             — all PHCs with lat/lon + stock health
GET /analytics/expiry-watchlist        — items expiring within N days across network
GET /analytics/top-alerts              — top N most critical alerts network-wide
GET /analytics/orders-overview         — pipeline counts + recent orders
"""

from typing import List, Optional
from datetime import date, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database    import get_db
from app.models.phc       import PHC
from app.models.inventory import InventoryItem, StockStatus
from app.models.order     import Order, OrderStatus

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/district-summary")
def district_summary(db: Session = Depends(get_db)):
    """Per-district breakdown of inventory health."""
    rows = (
        db.query(
            PHC.district,
            InventoryItem.stock_status,
            func.count(InventoryItem.id).label("count"),
        )
        .join(InventoryItem, InventoryItem.phc_id == PHC.id)
        .group_by(PHC.district, InventoryItem.stock_status)
        .all()
    )

    summary: dict = {}
    for district, status, count in rows:
        if district not in summary:
            summary[district] = {s.value: 0 for s in StockStatus}
        summary[district][status.value] += count

    return summary


@router.get("/network-map")
def network_map(db: Session = Depends(get_db)):
    """
    All active PHCs with coordinates and aggregate stock health.
    Used by the admin dashboard map to colour-code pins.
    health values: "healthy" | "at_risk" | "critical"
    """
    phcs = db.query(PHC).filter(PHC.is_active == True).all()
    result = []

    for phc in phcs:
        items = db.query(InventoryItem).filter(InventoryItem.phc_id == phc.id).all()
        total   = len(items)
        at_risk = sum(
            1 for i in items
            if i.stock_status in (StockStatus.LOW, StockStatus.CRITICAL,
                                   StockStatus.EXPIRED, StockStatus.EXPIRING)
        )
        if at_risk == 0:
            health = "healthy"
        elif total > 0 and at_risk > total * 0.3:
            health = "critical"
        else:
            health = "at_risk"

        result.append({
            "id":            phc.id,
            "phc_code":      phc.phc_code,
            "name":          phc.name,
            "district":      phc.district,
            "block":         phc.block,
            "latitude":      phc.latitude,
            "longitude":     phc.longitude,
            "total_items":   total,
            "at_risk_items": at_risk,
            "health":        health,
        })

    return result


@router.get("/expiry-watchlist")
def expiry_watchlist(
    days: int = Query(30, ge=1, le=180),
    db: Session = Depends(get_db),
):
    """Items expiring within `days` days, sorted by soonest expiry first."""
    cutoff = date.today() + timedelta(days=days)
    items = (
        db.query(InventoryItem)
        .join(PHC, PHC.id == InventoryItem.phc_id)
        .filter(
            InventoryItem.expiry_date != None,
            InventoryItem.expiry_date <= cutoff,
            InventoryItem.quantity_on_hand > 0,
        )
        .order_by(InventoryItem.expiry_date.asc())
        .all()
    )

    return [
        {
            "inventory_item_id": i.id,
            "phc_id":            i.phc_id,
            "nlem_code":         i.nlem_code,
            "drug_name":         i.drug_name,
            "batch_no":          i.batch_no,
            "quantity_on_hand":  i.quantity_on_hand,
            "expiry_date":       i.expiry_date.isoformat() if i.expiry_date else None,
            "days_until_expiry": (i.expiry_date - date.today()).days if i.expiry_date else None,
            "stock_status":      i.stock_status.value,
        }
        for i in items
    ]


@router.get("/top-alerts")
def top_alerts(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Most critical inventory alerts across the network."""
    priority_order = {
        StockStatus.CRITICAL: 0,
        StockStatus.LOW:      1,
        StockStatus.EXPIRING: 2,
        StockStatus.EXPIRED:  3,
    }
    items = (
        db.query(InventoryItem)
        .join(PHC, PHC.id == InventoryItem.phc_id)
        .filter(InventoryItem.stock_status.in_(list(priority_order.keys())))
        .all()
    )

    def sort_key(i: InventoryItem):
        pri = priority_order.get(i.stock_status, 9)
        days_left = (
            i.quantity_on_hand / i.avg_daily_consumption
            if i.avg_daily_consumption > 0 else 999
        )
        return (pri, days_left)

    items.sort(key=sort_key)
    top = items[:limit]

    return [
        {
            "inventory_item_id":       i.id,
            "phc_id":                  i.phc_id,
            "nlem_code":               i.nlem_code,
            "drug_name":               i.drug_name,
            "quantity_on_hand":        i.quantity_on_hand,
            "reorder_point":           round(i.reorder_point, 1),
            "avg_daily_consumption":   i.avg_daily_consumption,
            "days_of_stock_remaining": round(
                i.quantity_on_hand / i.avg_daily_consumption, 1
            ) if i.avg_daily_consumption > 0 else None,
            "stock_status":            i.stock_status.value,
            "expiry_date":             i.expiry_date.isoformat() if i.expiry_date else None,
        }
        for i in top
    ]


@router.get("/orders-overview")
def orders_overview(
    phc_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Pipeline counts + recent order list for dashboard widgets."""
    q = db.query(Order)
    if phc_id:
        q = q.filter(Order.phc_id == phc_id)

    pipeline = {s.value: 0 for s in OrderStatus}
    for order in q.all():
        pipeline[order.status.value] += 1

    recent_q = db.query(Order)
    if phc_id:
        recent_q = recent_q.filter(Order.phc_id == phc_id)
    recent = recent_q.order_by(Order.created_at.desc()).limit(10).all()

    return {
        "pipeline_counts": pipeline,
        "recent_orders": [
            {
                "id":         o.id,
                "phc_id":     o.phc_id,
                "drug_name":  o.drug_name,
                "quantity":   o.quantity_ordered,
                "status":     o.status.value,
                "order_type": o.order_type.value,
                "created_at": o.created_at.isoformat() if o.created_at else None,
            }
            for o in recent
        ],
    }
