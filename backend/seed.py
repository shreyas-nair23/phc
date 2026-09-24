"""
Data Seeding Script — PHC Supply Chain (Chikkaballapur District, Karnataka)
============================================================================
Matches the frontend dashboard (merge.html) exactly:
  • 9 PHCs across Chikkaballapur district taluks
  • 4 district vendors
  • 30 NLEM 2022 essential medicines per PHC (~270 inventory rows)
  • ~200 synthetic orders in various pipeline states

Run from the backend/ directory:
    python seed.py

Reseed from scratch:
    python seed.py --reset
"""

import argparse
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.core.database  import engine, SessionLocal, Base
from app.models.phc       import PHC
from app.models.inventory import InventoryItem, StockStatus
from app.models.vendor    import Vendor
from app.models.order     import Order, OrderStatus, OrderType
from app.core.demand_engine import compute_reorder_point, classify_stock_status

random.seed(42)

# ─────────────────────────────────────────────────────────────────────────────
# PHC MASTER DATA — Chikkaballapur District, Karnataka
# Matches the frontend IDs, names, and taluks exactly
# ─────────────────────────────────────────────────────────────────────────────

PHC_MASTER = [
    {
        "frontend_id": "PHC-014",
        "name":     "Gudibande PHC",
        "phc_code": "PHC-CKB-001",
        "district": "Chikkaballapur",
        "block":    "Gudibande",
        "village":  "Gudibande",
        "lat": 13.8800,
        "lon": 77.7700,
        "lang": "Kannada",
    },
    {
        "frontend_id": "PHC-021",
        "name":     "Chintamani PHC",
        "phc_code": "PHC-CKB-002",
        "district": "Chikkaballapur",
        "block":    "Chintamani",
        "village":  "Chintamani",
        "lat": 13.4006,
        "lon": 78.0592,
        "lang": "Kannada",
    },
    {
        "frontend_id": "PHC-009",
        "name":     "Bagepalli PHC",
        "phc_code": "PHC-CKB-003",
        "district": "Chikkaballapur",
        "block":    "Bagepalli",
        "village":  "Bagepalli",
        "lat": 13.7837,
        "lon": 77.7959,
        "lang": "Kannada",
    },
    {
        "frontend_id": "PHC-003",
        "name":     "Sidlaghatta PHC",
        "phc_code": "PHC-CKB-004",
        "district": "Chikkaballapur",
        "block":    "Sidlaghatta",
        "village":  "Sidlaghatta",
        "lat": 13.3882,
        "lon": 77.8651,
        "lang": "Kannada",
    },
    {
        "frontend_id": "PHC-007",
        "name":     "Chikkaballapur Rural PHC",
        "phc_code": "PHC-CKB-005",
        "district": "Chikkaballapur",
        "block":    "Chikkaballapur",
        "village":  "Chikkaballapur",
        "lat": 13.4355,
        "lon": 77.7275,
        "lang": "Kannada",
    },
    {
        "frontend_id": "PHC-012",
        "name":     "Gauribidanur PHC",
        "phc_code": "PHC-CKB-006",
        "district": "Chikkaballapur",
        "block":    "Gauribidanur",
        "village":  "Gauribidanur",
        "lat": 13.6112,
        "lon": 77.5181,
        "lang": "Kannada",
    },
    {
        "frontend_id": "PHC-002",
        "name":     "Manchenahalli PHC",
        "phc_code": "PHC-CKB-007",
        "district": "Chikkaballapur",
        "block":    "Chikkaballapur",
        "village":  "Manchenahalli",
        "lat": 13.4600,
        "lon": 77.7450,
        "lang": "Kannada",
    },
    {
        "frontend_id": "PHC-025",
        "name":     "Bashettahalli PHC",
        "phc_code": "PHC-CKB-008",
        "district": "Chikkaballapur",
        "block":    "Chikkaballapur",
        "village":  "Bashettahalli",
        "lat": 13.4200,
        "lon": 77.7600,
        "lang": "Kannada",
    },
    {
        "frontend_id": "PHC-030",
        "name":     "Perisandra PHC",
        "phc_code": "PHC-CKB-009",
        "district": "Chikkaballapur",
        "block":    "Gudibande",
        "village":  "Perisandra",
        "lat": 13.7200,
        "lon": 77.7400,
        "lang": "Kannada",
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# VENDOR MASTER DATA — Karnataka medical suppliers
# ─────────────────────────────────────────────────────────────────────────────

VENDOR_MASTER = [
    {
        "name":      "Southern Pharma Distributors",
        "code":      "VND-CKB-01",
        "district":  "Chikkaballapur",
        "phone":     "9845001001",
        "lang":      "Kannada",
        "lead_days": 5,
    },
    {
        "name":      "Karnataka Medical Supplies Co.",
        "code":      "VND-CKB-02",
        "district":  "Chikkaballapur",
        "phone":     "9845001002",
        "lang":      "Kannada",
        "lead_days": 6,
    },
    {
        "name":      "Vijaya Drug House",
        "code":      "VND-CKB-03",
        "district":  "Chikkaballapur",
        "phone":     "9845001003",
        "lang":      "Kannada",
        "lead_days": 7,
    },
    {
        "name":      "Karnataka State Medical Supplies Corp",
        "code":      "VND-KAR-01",
        "district":  "Chikkaballapur",
        "phone":     "9845002001",
        "lang":      "Kannada",
        "lead_days": 4,
    },
]

# Primary vendor for the district
DISTRICT_PRIMARY_VENDOR = "VND-CKB-01"

# ─────────────────────────────────────────────────────────────────────────────
# NLEM 2022 MEDICINES (30 items)
# ─────────────────────────────────────────────────────────────────────────────

NLEM_MEDICINES = [
    # Analgesics / Antipyretics
    {"nlem_code": "NLEM-001", "drug_name": "Paracetamol",            "generic_name": "Acetaminophen",           "form": "Tablet",    "strength": "500 mg",       "unit": "tablets",  "avg_daily": (15, 40)},
    {"nlem_code": "NLEM-002", "drug_name": "Ibuprofen",              "generic_name": "Ibuprofen",                "form": "Tablet",    "strength": "400 mg",       "unit": "tablets",  "avg_daily": (5,  20)},
    {"nlem_code": "NLEM-003", "drug_name": "Aspirin",                "generic_name": "Acetylsalicylic Acid",    "form": "Tablet",    "strength": "75 mg",        "unit": "tablets",  "avg_daily": (3,  10)},
    # Antibiotics
    {"nlem_code": "NLEM-010", "drug_name": "Amoxicillin",            "generic_name": "Amoxicillin",             "form": "Capsule",   "strength": "500 mg",       "unit": "capsules", "avg_daily": (10, 30)},
    {"nlem_code": "NLEM-011", "drug_name": "Cotrimoxazole",          "generic_name": "Sulfamethoxazole+TMP",    "form": "Tablet",    "strength": "480 mg",       "unit": "tablets",  "avg_daily": (5,  15)},
    {"nlem_code": "NLEM-012", "drug_name": "Metronidazole",          "generic_name": "Metronidazole",           "form": "Tablet",    "strength": "400 mg",       "unit": "tablets",  "avg_daily": (8,  25)},
    {"nlem_code": "NLEM-013", "drug_name": "Ciprofloxacin",          "generic_name": "Ciprofloxacin",           "form": "Tablet",    "strength": "500 mg",       "unit": "tablets",  "avg_daily": (4,  12)},
    {"nlem_code": "NLEM-014", "drug_name": "Doxycycline",            "generic_name": "Doxycycline Hyclate",     "form": "Capsule",   "strength": "100 mg",       "unit": "capsules", "avg_daily": (3,  10)},
    {"nlem_code": "NLEM-015", "drug_name": "Azithromycin",           "generic_name": "Azithromycin",            "form": "Tablet",    "strength": "500 mg",       "unit": "tablets",  "avg_daily": (3,  8) },
    {"nlem_code": "NLEM-016", "drug_name": "Benzylpenicillin",       "generic_name": "Penicillin G",            "form": "Injection", "strength": "10 lac IU",    "unit": "vials",    "avg_daily": (1,  5) },
    # Anti-malarials
    {"nlem_code": "NLEM-020", "drug_name": "Chloroquine Phosphate",  "generic_name": "Chloroquine",             "form": "Tablet",    "strength": "250 mg",       "unit": "tablets",  "avg_daily": (4,  12)},
    {"nlem_code": "NLEM-021", "drug_name": "Artesunate",             "generic_name": "Artesunate",              "form": "Tablet",    "strength": "50 mg",        "unit": "tablets",  "avg_daily": (2,  8) },
    {"nlem_code": "NLEM-022", "drug_name": "Primaquine",             "generic_name": "Primaquine Phosphate",    "form": "Tablet",    "strength": "7.5 mg",       "unit": "tablets",  "avg_daily": (2,  6) },
    # Anti-tuberculosis
    {"nlem_code": "NLEM-030", "drug_name": "Rifampicin",             "generic_name": "Rifampicin",              "form": "Tablet",    "strength": "450 mg",       "unit": "tablets",  "avg_daily": (3,  8) },
    {"nlem_code": "NLEM-031", "drug_name": "Isoniazid",              "generic_name": "Isoniazid",               "form": "Tablet",    "strength": "300 mg",       "unit": "tablets",  "avg_daily": (3,  8) },
    {"nlem_code": "NLEM-032", "drug_name": "Pyrazinamide",           "generic_name": "Pyrazinamide",            "form": "Tablet",    "strength": "500 mg",       "unit": "tablets",  "avg_daily": (3,  8) },
    # ORS & Nutrition
    {"nlem_code": "NLEM-040", "drug_name": "ORS Powder",             "generic_name": "Oral Rehydration Salts",  "form": "Sachet",    "strength": "WHO formula",  "unit": "sachets",  "avg_daily": (10, 50)},
    {"nlem_code": "NLEM-041", "drug_name": "Zinc Sulphate",          "generic_name": "Zinc Sulfate",            "form": "Tablet",    "strength": "20 mg",        "unit": "tablets",  "avg_daily": (5,  20)},
    {"nlem_code": "NLEM-042", "drug_name": "Iron Folic Acid",        "generic_name": "Ferrous Sulfate + FA",    "form": "Tablet",    "strength": "100 mg+0.5 mg","unit": "tablets",  "avg_daily": (8,  25)},
    # Cardiovascular
    {"nlem_code": "NLEM-050", "drug_name": "Atenolol",               "generic_name": "Atenolol",                "form": "Tablet",    "strength": "50 mg",        "unit": "tablets",  "avg_daily": (3,  10)},
    {"nlem_code": "NLEM-051", "drug_name": "Amlodipine",             "generic_name": "Amlodipine Besylate",     "form": "Tablet",    "strength": "5 mg",         "unit": "tablets",  "avg_daily": (4,  12)},
    {"nlem_code": "NLEM-052", "drug_name": "Enalapril",              "generic_name": "Enalapril Maleate",       "form": "Tablet",    "strength": "5 mg",         "unit": "tablets",  "avg_daily": (3,  10)},
    # Diabetes
    {"nlem_code": "NLEM-060", "drug_name": "Metformin",              "generic_name": "Metformin HCl",           "form": "Tablet",    "strength": "500 mg",       "unit": "tablets",  "avg_daily": (6,  20)},
    {"nlem_code": "NLEM-061", "drug_name": "Glibenclamide",          "generic_name": "Glibenclamide",           "form": "Tablet",    "strength": "5 mg",         "unit": "tablets",  "avg_daily": (3,  10)},
    # Respiratory
    {"nlem_code": "NLEM-070", "drug_name": "Salbutamol Inhaler",     "generic_name": "Albuterol",               "form": "Inhaler",   "strength": "100 mcg/dose", "unit": "inhalers", "avg_daily": (0,  2) },
    {"nlem_code": "NLEM-071", "drug_name": "Prednisolone",           "generic_name": "Prednisolone",            "form": "Tablet",    "strength": "5 mg",         "unit": "tablets",  "avg_daily": (3,  10)},
    # Vitamins
    {"nlem_code": "NLEM-080", "drug_name": "Vitamin A",              "generic_name": "Retinol",                 "form": "Capsule",   "strength": "1 lakh IU",    "unit": "capsules", "avg_daily": (1,  5) },
    {"nlem_code": "NLEM-081", "drug_name": "Vitamin B Complex",      "generic_name": "B1+B2+B6+B12",            "form": "Tablet",    "strength": "Standard",     "unit": "tablets",  "avg_daily": (4,  12)},
    # Vaccines (stock tracking)
    {"nlem_code": "NLEM-090", "drug_name": "OPV Vaccine",            "generic_name": "Oral Polio Vaccine",      "form": "Vial",      "strength": "10 dose",      "unit": "vials",    "avg_daily": (0,  3) },
    {"nlem_code": "NLEM-091", "drug_name": "BCG Vaccine",            "generic_name": "Bacillus Calmette-Guerin","form": "Vial",      "strength": "10 dose",      "unit": "vials",    "avg_daily": (0,  2) },
    # Antiseptics
    {"nlem_code": "NLEM-100", "drug_name": "Povidone Iodine",        "generic_name": "Povidone Iodine",         "form": "Solution",  "strength": "5%",           "unit": "bottles",  "avg_daily": (0,  3) },
]


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _random_batch() -> str:
    prefix = random.choice(["BT", "KA", "CB", "PH"])
    return f"{prefix}{random.randint(10000, 99999)}"


def _random_expiry(months_min: int = 3, months_max: int = 36) -> date:
    days = random.randint(months_min * 30, months_max * 30)
    return date.today() + timedelta(days=days)


def _expiry_with_risk() -> date:
    """Occasionally produce expiring-soon or expired batches for realism."""
    roll = random.random()
    today = date.today()
    if roll < 0.05:    # 5%  → already expired
        return today - timedelta(days=random.randint(1, 30))
    elif roll < 0.15:  # 10% → expiring within 30 days
        return today + timedelta(days=random.randint(1, 29))
    return _random_expiry()


def _quantity_with_risk(rop: float, avg_daily: float) -> int:
    """
    Produce realistic quantity distribution:
      15% critically low  (≤ 3 days stock)
      20% at reorder point
      65% healthy
    """
    roll = random.random()
    if roll < 0.15:
        return max(0, int(avg_daily * random.uniform(0, 3)))
    elif roll < 0.35:
        return max(0, int(rop * random.uniform(0.5, 1.0)))
    return int(rop * random.uniform(1.5, 5.0))


# ─────────────────────────────────────────────────────────────────────────────
# SEED FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def seed_phcs(db) -> dict:
    """Insert PHC rows; return {phc_code: PHC} map."""
    phc_map = {}
    contact_names = ["Dr. Ravi Kumar", "Dr. Priya Gowda", "Dr. Suresh Naik",
                     "Dr. Anitha Reddy", "Dr. Manjunath", "Dr. Kavitha S",
                     "Dr. Venkatesh", "Dr. Suma Devi", "Dr. Prakash R"]
    for i, p in enumerate(PHC_MASTER):
        phc = PHC(
            name          = p["name"],
            phc_code      = p["phc_code"],
            district      = p["district"],
            state         = "Karnataka",
            block         = p["block"],
            village       = p["village"],
            latitude      = p["lat"] + random.uniform(-0.005, 0.005),
            longitude     = p["lon"] + random.uniform(-0.005, 0.005),
            contact_name  = contact_names[i % len(contact_names)],
            contact_phone = f"98{random.randint(10000000, 99999999)}",
            language      = p["lang"],
            is_active     = True,
        )
        db.add(phc)
        phc_map[p["phc_code"]] = phc

    db.flush()
    print(f"  ✓ Seeded {len(PHC_MASTER)} PHCs (Chikkaballapur district, Karnataka)")
    return phc_map


def seed_vendors(db) -> dict:
    """Insert Vendor rows; return {vendor_code: Vendor} map."""
    vendor_map = {}
    for v in VENDOR_MASTER:
        vendor = Vendor(
            name              = v["name"],
            vendor_code       = v["code"],
            district          = v["district"],
            state             = "Karnataka",
            contact_name      = f"Mr. {random.choice(['Suresh', 'Ramesh', 'Ganesh', 'Mahesh'])} Kumar",
            phone             = v["phone"],
            whatsapp          = v["phone"],
            preferred_lang    = v["lang"],
            avg_lead_days     = v["lead_days"],
            service_radius_km = random.choice([30.0, 50.0, 75.0]),
            is_active         = True,
        )
        db.add(vendor)
        vendor_map[v["code"]] = vendor

    db.flush()
    print(f"  ✓ Seeded {len(VENDOR_MASTER)} vendors")
    return vendor_map


def seed_inventory(db, phc_map: dict) -> None:
    """Insert InventoryItem rows for every PHC × every NLEM drug."""
    count = 0
    for phc in phc_map.values():
        for drug in NLEM_MEDICINES:
            avg_min, avg_max = drug["avg_daily"]
            avg_daily   = round(random.uniform(avg_min, avg_max), 1)
            lead_days   = random.randint(4, 8)
            safety_days = random.randint(3, 7)

            rop    = compute_reorder_point(avg_daily, lead_days, safety_days)
            qty    = _quantity_with_risk(rop, avg_daily)
            expiry = _expiry_with_risk()

            status = classify_stock_status(
                quantity_on_hand=qty,
                reorder_point=rop,
                avg_daily_consumption=avg_daily,
                expiry_date=expiry,
            )

            item = InventoryItem(
                phc_id                = phc.id,
                nlem_code             = drug["nlem_code"],
                drug_name             = drug["drug_name"],
                generic_name          = drug["generic_name"],
                dosage_form           = drug["form"],
                strength              = drug["strength"],
                unit                  = drug["unit"],
                batch_no              = _random_batch(),
                quantity_on_hand      = qty,
                expiry_date           = expiry,
                avg_daily_consumption = avg_daily,
                supplier_lead_days    = lead_days,
                safety_stock_days     = safety_days,
                reorder_point         = rop,
                max_stock_level       = int(avg_daily * 60),
                stock_status          = status,
            )
            db.add(item)
            count += 1

    db.flush()
    print(f"  ✓ Seeded {count} inventory rows ({len(phc_map)} PHCs × {len(NLEM_MEDICINES)} drugs)")


def seed_orders(db, phc_map: dict, vendor_map: dict) -> None:
    """Generate ~200 synthetic orders matching the frontend pipeline stages."""
    phcs = list(phc_map.values())

    # These vendor names match what the frontend order demo data shows
    primary_vendor   = vendor_map.get(DISTRICT_PRIMARY_VENDOR)
    secondary_vendor = vendor_map.get("VND-CKB-02")
    tertiary_vendor  = vendor_map.get("VND-CKB-03")

    vendor_pool = [v for v in [primary_vendor, secondary_vendor, tertiary_vendor] if v]

    statuses = [
        OrderStatus.REQUISITION_SENT,
        OrderStatus.VENDOR_CONFIRMED,
        OrderStatus.IN_TRANSIT,
        OrderStatus.DELIVERED,
        OrderStatus.VERIFIED,
    ]
    status_weights = [0.20, 0.20, 0.25, 0.20, 0.15]

    count = 0
    for _ in range(200):
        phc    = random.choice(phcs)
        drug   = random.choice(NLEM_MEDICINES)
        status = random.choices(statuses, weights=status_weights, k=1)[0]
        vendor = random.choice(vendor_pool) if vendor_pool else None

        today          = date.today()
        created_offset = random.randint(0, 30)
        lead_days      = random.randint(4, 8)
        exp_delivery   = today - timedelta(days=created_offset) + timedelta(days=lead_days)

        qty_ordered   = random.randint(50, 500)
        qty_delivered = (
            random.randint(int(qty_ordered * 0.8), qty_ordered)
            if status in (OrderStatus.DELIVERED, OrderStatus.VERIFIED)
            else None
        )
        actual_delivery = (
            exp_delivery + timedelta(days=random.randint(-2, 3))
            if status in (OrderStatus.DELIVERED, OrderStatus.VERIFIED)
            else None
        )

        order = Order(
            phc_id                 = phc.id,
            vendor_id              = vendor.id if vendor else None,
            order_type             = OrderType.VENDOR_ORDER,
            status                 = status,
            nlem_code              = drug["nlem_code"],
            drug_name              = drug["drug_name"],
            quantity_ordered       = qty_ordered,
            quantity_delivered     = qty_delivered,
            expected_delivery_date = exp_delivery,
            actual_delivery_date   = actual_delivery,
            is_auto_generated      = random.choice([True, False]),
            sms_sent               = status != OrderStatus.DRAFT,
            sms_language           = phc.language,
        )
        db.add(order)
        count += 1

    # Add inter-PHC transfer orders
    for _ in range(20):
        source = random.choice(phcs)
        target = random.choice([p for p in phcs if p.id != source.id])
        drug   = random.choice(NLEM_MEDICINES)

        order = Order(
            phc_id           = target.id,
            source_phc_id    = source.id,
            order_type       = OrderType.INTER_PHC,
            status           = random.choice([
                OrderStatus.REQUISITION_SENT,
                OrderStatus.IN_TRANSIT,
                OrderStatus.DELIVERED,
            ]),
            nlem_code         = drug["nlem_code"],
            drug_name         = drug["drug_name"],
            quantity_ordered  = random.randint(20, 150),
            is_auto_generated = True,
            sms_sent          = True,
            sms_language      = target.language,
        )
        db.add(order)
        count += 1

    db.flush()
    print(f"  ✓ Seeded {count} orders")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main(reset: bool = False) -> None:
    print("\n══ PHC Supply Chain — Database Seeder (Chikkaballapur, Karnataka) ══")

    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        if reset:
            print("  ⚠  --reset: dropping all rows …")
            db.query(Order).delete()
            db.query(InventoryItem).delete()
            db.query(Vendor).delete()
            db.query(PHC).delete()
            db.commit()
            print("  ✓ Tables cleared")

        if db.query(PHC).count() > 0 and not reset:
            print("  ℹ  Database already seeded. Use --reset to reseed.")
            return

        print("\n  Seeding …")
        phc_map    = seed_phcs(db)
        vendor_map = seed_vendors(db)
        seed_inventory(db, phc_map)
        seed_orders(db, phc_map, vendor_map)

        db.commit()
        print(f"\n  ✓ Seed complete.")
        print(f"    PHCs      : {db.query(PHC).count()}")
        print(f"    Vendors   : {db.query(Vendor).count()}")
        print(f"    Inventory : {db.query(InventoryItem).count()}")
        print(f"    Orders    : {db.query(Order).count()}")
        print("═════════════════════════════════════════════════════════════\n")

    except Exception as exc:
        db.rollback()
        print(f"\n  ✗ Seeding failed: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the PHC database.")
    parser.add_argument("--reset", action="store_true", help="Wipe existing data before seeding")
    args = parser.parse_args()
    main(reset=args.reset)
