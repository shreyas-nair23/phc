"""
Demand Engine — Core Business Logic
=====================================
Responsibilities:
  1. compute_reorder_point()     — dynamic ROP based on consumption velocity + lead time
  2. compute_eoq()               — Economic Order Quantity to minimise ordering cost
  3. classify_stock_status()     — assign HEALTHY / LOW / CRITICAL / EXPIRED / EXPIRING
  4. days_of_stock_remaining()   — how many days until stock hits zero
  5. run_reorder_scan()          — scan all inventory rows for a PHC, return alerts
  6. haversine_distance_km()     — great-circle distance between two lat/lon points
  7. find_inter_phc_transfers()  — identify nearby PHCs with surplus for emergency transfer
  8. refresh_all_reorder_points()— bulk-update reorder_point column for all items
"""

import math
from datetime import date, timedelta
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.inventory import InventoryItem, StockStatus
from app.models.phc       import PHC
from app.schemas.schemas  import StockAlertRead, TransferSuggestion


# ─────────────────────────────────────────────────────────────────────────────
# 1. REORDER POINT
# ─────────────────────────────────────────────────────────────────────────────

def compute_reorder_point(
    avg_daily_consumption: float,
    supplier_lead_days: int,
    safety_stock_days: int = 5,
) -> float:
    """
    Reorder Point (ROP) = average daily consumption × (lead time + safety buffer)
    """
    if avg_daily_consumption <= 0:
        return 0.0
    return avg_daily_consumption * (supplier_lead_days + safety_stock_days)


# ─────────────────────────────────────────────────────────────────────────────
# 2. ECONOMIC ORDER QUANTITY
# ─────────────────────────────────────────────────────────────────────────────

def compute_eoq(
    annual_demand: float,
    ordering_cost: float = 50.0,
    holding_cost_per_unit: float = 2.0,
) -> float:
    """EOQ = sqrt( (2 × D × S) / H )"""
    if annual_demand <= 0 or holding_cost_per_unit <= 0:
        return 0.0
    return math.sqrt((2 * annual_demand * ordering_cost) / holding_cost_per_unit)


# ─────────────────────────────────────────────────────────────────────────────
# 3. STOCK STATUS CLASSIFICATION
# ─────────────────────────────────────────────────────────────────────────────

EXPIRY_WARN_DAYS = 30

def classify_stock_status(
    quantity_on_hand: int,
    reorder_point: float,
    avg_daily_consumption: float,
    expiry_date: Optional[date] = None,
    critical_days_threshold: int = 3,
) -> StockStatus:
    """
    Priority order: EXPIRED > EXPIRING > CRITICAL > LOW > HEALTHY
    """
    today = date.today()

    if expiry_date:
        if expiry_date <= today:
            return StockStatus.EXPIRED
        if (expiry_date - today).days <= EXPIRY_WARN_DAYS:
            return StockStatus.EXPIRING

    if avg_daily_consumption > 0:
        days_left = quantity_on_hand / avg_daily_consumption
        if days_left <= critical_days_threshold:
            return StockStatus.CRITICAL

    if quantity_on_hand <= reorder_point:
        return StockStatus.LOW

    return StockStatus.HEALTHY


# ─────────────────────────────────────────────────────────────────────────────
# 4. DAYS OF STOCK REMAINING
# ─────────────────────────────────────────────────────────────────────────────

def days_of_stock_remaining(
    quantity_on_hand: int,
    avg_daily_consumption: float,
) -> Optional[float]:
    if avg_daily_consumption <= 0:
        return None
    return round(quantity_on_hand / avg_daily_consumption, 1)


# ─────────────────────────────────────────────────────────────────────────────
# 5. REORDER SCAN
# ─────────────────────────────────────────────────────────────────────────────

def run_reorder_scan(db: Session, phc_id: int) -> List[StockAlertRead]:
    """
    Scan every inventory item for a given PHC.
    Re-computes each item's reorder_point and stock_status, persists updates,
    returns a list of StockAlertRead for non-healthy items.
    """
    phc = db.query(PHC).filter(PHC.id == phc_id).first()
    if not phc:
        return []

    items: List[InventoryItem] = (
        db.query(InventoryItem)
        .filter(InventoryItem.phc_id == phc_id)
        .all()
    )

    alerts: List[StockAlertRead] = []

    for item in items:
        rop = compute_reorder_point(
            item.avg_daily_consumption,
            item.supplier_lead_days,
            item.safety_stock_days,
        )
        item.reorder_point = rop

        status = classify_stock_status(
            quantity_on_hand=item.quantity_on_hand,
            reorder_point=rop,
            avg_daily_consumption=item.avg_daily_consumption,
            expiry_date=item.expiry_date,
        )
        item.stock_status = status

        if status != StockStatus.HEALTHY:
            alerts.append(
                StockAlertRead(
                    inventory_item_id=item.id,
                    phc_id=phc_id,
                    phc_name=phc.name,
                    nlem_code=item.nlem_code,
                    drug_name=item.drug_name,
                    quantity_on_hand=item.quantity_on_hand,
                    reorder_point=rop,
                    stock_status=status,
                    days_of_stock_remaining=days_of_stock_remaining(
                        item.quantity_on_hand, item.avg_daily_consumption
                    ),
                    expiry_date=item.expiry_date,
                )
            )

    db.commit()
    return alerts


def run_network_reorder_scan(db: Session) -> List[StockAlertRead]:
    """Run run_reorder_scan across ALL active PHCs in the network."""
    phc_ids = [row.id for row in db.query(PHC.id).filter(PHC.is_active == True).all()]
    all_alerts: List[StockAlertRead] = []
    for phc_id in phc_ids:
        all_alerts.extend(run_reorder_scan(db, phc_id))
    return all_alerts


# ─────────────────────────────────────────────────────────────────────────────
# 6. HAVERSINE DISTANCE
# ─────────────────────────────────────────────────────────────────────────────

EARTH_RADIUS_KM = 6371.0

def haversine_distance_km(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
) -> float:
    """Great-circle distance between two WGS-84 coordinates."""
    φ1 = math.radians(lat1)
    φ2 = math.radians(lat2)
    Δφ = math.radians(lat2 - lat1)
    Δλ = math.radians(lon2 - lon1)

    a = math.sin(Δφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(Δλ / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return round(EARTH_RADIUS_KM * c, 2)


def get_phcs_within_radius(
    db: Session,
    origin_phc_id: int,
    radius_km: float = 20.0,
) -> List[Tuple[PHC, float]]:
    """Return all active PHCs within radius_km of origin_phc_id, sorted nearest-first."""
    origin: Optional[PHC] = db.query(PHC).filter(PHC.id == origin_phc_id).first()
    if not origin:
        return []

    candidates = (
        db.query(PHC)
        .filter(PHC.is_active == True, PHC.id != origin_phc_id)
        .all()
    )

    nearby: List[Tuple[PHC, float]] = []
    for phc in candidates:
        dist = haversine_distance_km(
            origin.latitude, origin.longitude,
            phc.latitude,   phc.longitude,
        )
        if dist <= radius_km:
            nearby.append((phc, dist))

    nearby.sort(key=lambda t: t[1])
    return nearby


# ─────────────────────────────────────────────────────────────────────────────
# 7. INTER-PHC TRANSFER SUGGESTIONS
# ─────────────────────────────────────────────────────────────────────────────

SURPLUS_MULTIPLIER = 2.0

def find_inter_phc_transfers(
    db: Session,
    target_phc_id: int,
    radius_km: float = 20.0,
) -> List[TransferSuggestion]:
    """
    For each LOW / CRITICAL drug at the target PHC, search nearby PHCs
    within radius_km for surplus stock of the same drug.
    """
    needy_items: List[InventoryItem] = (
        db.query(InventoryItem)
        .filter(
            InventoryItem.phc_id == target_phc_id,
            InventoryItem.stock_status.in_([StockStatus.LOW, StockStatus.CRITICAL]),
        )
        .all()
    )
    if not needy_items:
        return []

    nearby_phcs = get_phcs_within_radius(db, target_phc_id, radius_km)
    if not nearby_phcs:
        return []

    target_phc: Optional[PHC] = db.query(PHC).filter(PHC.id == target_phc_id).first()
    suggestions: List[TransferSuggestion] = []

    for needed_item in needy_items:
        for donor_phc, dist_km in nearby_phcs:
            donor_item: Optional[InventoryItem] = (
                db.query(InventoryItem)
                .filter(
                    InventoryItem.phc_id == donor_phc.id,
                    InventoryItem.nlem_code == needed_item.nlem_code,
                    InventoryItem.stock_status == StockStatus.HEALTHY,
                )
                .first()
            )
            if not donor_item:
                continue

            surplus_threshold = SURPLUS_MULTIPLIER * donor_item.reorder_point
            if donor_item.quantity_on_hand <= surplus_threshold:
                continue

            donor_surplus = donor_item.quantity_on_hand - surplus_threshold

            if needed_item.max_stock_level:
                target_need = needed_item.max_stock_level - needed_item.quantity_on_hand
            else:
                target_need = max(
                    0,
                    int(needed_item.avg_daily_consumption * 30) - needed_item.quantity_on_hand,
                )

            suggested_qty = int(min(donor_surplus, target_need))
            if suggested_qty <= 0:
                continue

            suggestions.append(
                TransferSuggestion(
                    source_phc_id=donor_phc.id,
                    source_phc_name=donor_phc.name,
                    target_phc_id=target_phc_id,
                    target_phc_name=target_phc.name,
                    nlem_code=needed_item.nlem_code,
                    drug_name=needed_item.drug_name,
                    suggested_qty=suggested_qty,
                    distance_km=dist_km,
                )
            )
            break

    return suggestions


# ─────────────────────────────────────────────────────────────────────────────
# 8. BULK REORDER-POINT REFRESH
# ─────────────────────────────────────────────────────────────────────────────

def refresh_all_reorder_points(db: Session) -> int:
    """Re-compute and persist reorder_point for every inventory item."""
    items: List[InventoryItem] = db.query(InventoryItem).all()
    for item in items:
        item.reorder_point = compute_reorder_point(
            item.avg_daily_consumption,
            item.supplier_lead_days,
            item.safety_stock_days,
        )
    db.commit()
    return len(items)
