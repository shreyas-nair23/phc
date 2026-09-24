"""
PHC Routes
GET    /phcs                     — list all PHCs (filterable by district/state)
POST   /phcs                     — create a new PHC
GET    /phcs/{phc_id}            — get single PHC
PATCH  /phcs/{phc_id}            — update PHC metadata
GET    /phcs/{phc_id}/inventory  — get all inventory for a PHC
GET    /phcs/{phc_id}/alerts     — run demand scan, return non-healthy items
GET    /phcs/{phc_id}/transfers  — get inter-PHC transfer suggestions
GET    /phcs/{phc_id}/nearby     — list nearby PHCs within radius
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database    import get_db
from app.core.demand_engine import (
    run_reorder_scan,
    find_inter_phc_transfers,
    get_phcs_within_radius,
)
from app.models.phc        import PHC
from app.models.inventory  import InventoryItem
from app.schemas.schemas   import (
    PHCCreate, PHCUpdate, PHCRead,
    InventoryItemRead,
    StockAlertRead,
    TransferSuggestion,
    MessageResponse,
)

router = APIRouter(prefix="/phcs", tags=["PHCs"])


@router.get("", response_model=List[PHCRead])
def list_phcs(
    district: Optional[str] = Query(None),
    state:    Optional[str] = Query(None),
    active:   Optional[bool] = Query(None),
    skip: int = Query(0,   ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(PHC)
    if district:
        q = q.filter(PHC.district.ilike(f"%{district}%"))
    if state:
        q = q.filter(PHC.state.ilike(f"%{state}%"))
    if active is not None:
        q = q.filter(PHC.is_active == active)
    return q.offset(skip).limit(limit).all()


@router.post("", response_model=PHCRead, status_code=201)
def create_phc(payload: PHCCreate, db: Session = Depends(get_db)):
    if db.query(PHC).filter(PHC.phc_code == payload.phc_code).first():
        raise HTTPException(status_code=409, detail=f"PHC code '{payload.phc_code}' already exists.")
    phc = PHC(**payload.model_dump())
    db.add(phc)
    db.commit()
    db.refresh(phc)
    return phc


@router.get("/{phc_id}", response_model=PHCRead)
def get_phc(phc_id: int, db: Session = Depends(get_db)):
    phc = db.query(PHC).filter(PHC.id == phc_id).first()
    if not phc:
        raise HTTPException(status_code=404, detail="PHC not found.")
    return phc


@router.patch("/{phc_id}", response_model=PHCRead)
def update_phc(phc_id: int, payload: PHCUpdate, db: Session = Depends(get_db)):
    phc = db.query(PHC).filter(PHC.id == phc_id).first()
    if not phc:
        raise HTTPException(status_code=404, detail="PHC not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(phc, field, value)
    db.commit()
    db.refresh(phc)
    return phc


@router.get("/{phc_id}/inventory", response_model=List[InventoryItemRead])
def get_phc_inventory(
    phc_id: int,
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    if not db.query(PHC).filter(PHC.id == phc_id).first():
        raise HTTPException(status_code=404, detail="PHC not found.")
    q = db.query(InventoryItem).filter(InventoryItem.phc_id == phc_id)
    if status:
        q = q.filter(InventoryItem.stock_status == status)
    return q.all()


@router.get("/{phc_id}/alerts", response_model=List[StockAlertRead])
def get_phc_alerts(phc_id: int, db: Session = Depends(get_db)):
    if not db.query(PHC).filter(PHC.id == phc_id).first():
        raise HTTPException(status_code=404, detail="PHC not found.")
    return run_reorder_scan(db, phc_id)


@router.get("/{phc_id}/transfers", response_model=List[TransferSuggestion])
def get_transfer_suggestions(
    phc_id: int,
    radius_km: float = Query(20.0, ge=1.0, le=100.0),
    db: Session = Depends(get_db),
):
    if not db.query(PHC).filter(PHC.id == phc_id).first():
        raise HTTPException(status_code=404, detail="PHC not found.")
    return find_inter_phc_transfers(db, phc_id, radius_km)


@router.get("/{phc_id}/nearby", response_model=List[dict])
def get_nearby_phcs(
    phc_id: int,
    radius_km: float = Query(20.0, ge=1.0, le=200.0),
    db: Session = Depends(get_db),
):
    if not db.query(PHC).filter(PHC.id == phc_id).first():
        raise HTTPException(status_code=404, detail="PHC not found.")
    nearby = get_phcs_within_radius(db, phc_id, radius_km)
    return [
        {
            "id":          phc.id,
            "phc_code":    phc.phc_code,
            "name":        phc.name,
            "district":    phc.district,
            "latitude":    phc.latitude,
            "longitude":   phc.longitude,
            "distance_km": dist,
        }
        for phc, dist in nearby
    ]
