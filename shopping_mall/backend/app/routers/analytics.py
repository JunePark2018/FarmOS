"""Analytics and customer segmentation router."""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.customer_segment import CustomerSegment
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.revenue import RevenueEntry
from app.models.expense import ExpenseEntry
from app.schemas.segment import CustomerSegmentResponse, SegmentSummary
from app.services.rfm_analyzer import RFMAnalyzer

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/segments", response_model=List[SegmentSummary])
def get_segment_summary(db: Session = Depends(get_db)):
    """Get summary of customer segments."""
    results = RFMAnalyzer.get_segment_summary(db)
    return results


@router.get("/segments/{segment}", response_model=List[CustomerSegmentResponse])
def get_customers_in_segment(segment: str, db: Session = Depends(get_db)):
    """Get all customers in a specific segment."""
    valid_segments = {"vip", "loyal", "repeat", "new", "at_risk", "dormant"}
    if segment not in valid_segments:
        raise HTTPException(status_code=400, detail=f"Invalid segment. Must be one of: {valid_segments}")
    customers = (
        db.query(CustomerSegment)
        .filter(CustomerSegment.segment == segment)
        .all()
    )
    return customers


@router.post("/segments/refresh")
def refresh_segments(db: Session = Depends(get_db)):
    """Recalculate all customer segments using RFM analysis."""
    count = RFMAnalyzer.analyze_all(db)
    return {"updated_count": count}


@router.get("/popular-items")
def get_popular_items(
    top_n: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Get top N popular items by sales count."""
    items = (
        db.query(
            Product.id,
            Product.name,
            Product.price,
            Product.sales_count,
            Product.rating,
            Product.thumbnail,
        )
        .order_by(Product.sales_count.desc())
        .limit(top_n)
        .all()
    )
    return [
        {
            "id": item.id,
            "name": item.name,
            "price": item.price,
            "salesCount": item.sales_count,
            "rating": item.rating,
            "thumbnail": item.thumbnail,
        }
        for item in items
    ]


@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db)):
    """Combined dashboard stats."""
    # Total revenue
    total_revenue = (
        db.query(func.coalesce(func.sum(RevenueEntry.total_amount), 0))
        .filter(RevenueEntry.category == "sales")
        .scalar()
    ) or 0

    # Total expenses
    total_expense = (
        db.query(func.coalesce(func.sum(ExpenseEntry.amount), 0)).scalar()
    ) or 0

    # Order stats
    total_orders = db.query(func.count(Order.id)).scalar() or 0
    pending_orders = (
        db.query(func.count(Order.id))
        .filter(Order.status == "pending")
        .scalar()
    ) or 0

    # Top 5 products
    top_products = (
        db.query(Product.name, Product.sales_count)
        .order_by(Product.sales_count.desc())
        .limit(5)
        .all()
    )

    # Segment summary
    segments = RFMAnalyzer.get_segment_summary(db)

    return {
        "totalRevenue": total_revenue,
        "totalExpense": total_expense,
        "netProfit": total_revenue - total_expense,
        "totalOrders": total_orders,
        "pendingOrders": pending_orders,
        "topProducts": [{"name": name, "salesCount": cnt} for name, cnt in top_products],
        "customerSegments": segments,
    }
