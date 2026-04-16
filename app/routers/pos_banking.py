from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from datetime import datetime, date, timedelta
from .. import models, auth
from ..database import get_db
from ..config import settings

router = APIRouter(prefix="/pos-banking", tags=["pos-banking"])
templates = Jinja2Templates(directory=settings.TEMPLATES_DIR)


def calculate_charge_from_total(db: Session, transaction_type: str, total: float) -> tuple:
    """
    Calculate charge and actual amount from the total entered by user.
    The total includes both the transaction amount and the charge (profit).
    Returns: (actual_amount, charge, config)

    Finds the tier where the back-calculated amount falls within the tier's range.
    Handles boundary gaps by allowing 1 unit tolerance on min_amount.
    """
    # Get all active configs for this transaction type, ordered by min_amount descending
    # (check higher tiers first to find the best match)
    configs = db.query(models.POSChargeConfig).filter(
        models.POSChargeConfig.transaction_type == transaction_type,
        models.POSChargeConfig.is_active == 1
    ).order_by(models.POSChargeConfig.min_amount.desc()).all()

    if not configs:
        return total, 0, None

    # Try each config - back-calculate amount and check if it fits the tier
    for config in configs:
        if config.charge_type == "percentage":
            # amount = total / (1 + percentage/100)
            multiplier = 1 + config.charge_value / 100
            actual_amount = total / multiplier
            charge = total - actual_amount
        else:
            # Fixed charge: amount = total - charge
            actual_amount = total - config.charge_value
            charge = config.charge_value

        # Check if the calculated amount falls within this tier's range
        # Allow 1 unit tolerance on min_amount to handle boundary gaps
        # e.g., if tier is 5001-10000 and amount is 5000, still match this tier
        if actual_amount >= (config.min_amount - 1) and actual_amount <= config.max_amount:
            return actual_amount, charge, config

    # If no tier matches, return total as amount with no charge
    return total, 0, None

    # If no tier matches, return total as amount with no charge
    return total, 0, None


@router.get("", response_class=HTMLResponse)
async def pos_banking_page(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    """Main POS banking page"""
    # Get today's transactions
    today = date.today()
    today_transactions = db.query(models.POSTransaction).filter(
        func.date(models.POSTransaction.created_at) == today
    ).order_by(models.POSTransaction.created_at.desc()).all()

    # Today's summary
    summary = db.query(
        func.sum(case((models.POSTransaction.transaction_type == 'withdrawal', models.POSTransaction.amount), else_=0)).label("total_withdrawals"),
        func.sum(case((models.POSTransaction.transaction_type == 'deposit', models.POSTransaction.amount), else_=0)).label("total_deposits"),
        func.sum(case((models.POSTransaction.transaction_type == 'withdrawal', models.POSTransaction.charge), else_=0)).label("withdrawal_charges"),
        func.sum(case((models.POSTransaction.transaction_type == 'deposit', models.POSTransaction.charge), else_=0)).label("deposit_charges"),
        func.count(case((models.POSTransaction.transaction_type == 'withdrawal', 1), else_=None)).label("withdrawal_count"),
        func.count(case((models.POSTransaction.transaction_type == 'deposit', 1), else_=None)).label("deposit_count")
    ).filter(
        func.date(models.POSTransaction.created_at) == today
    ).first()

    return templates.TemplateResponse(
        request, "pos_banking/index.html", {"user": user,
            "is_admin": user.role == "admin",
            "transactions": today_transactions,
            "summary": {
                "total_withdrawals": summary.total_withdrawals or 0,
                "total_deposits": summary.total_deposits or 0,
                "withdrawal_charges": summary.withdrawal_charges or 0,
                "deposit_charges": summary.deposit_charges or 0,
                "withdrawal_count": summary.withdrawal_count or 0,
                "deposit_count": summary.deposit_count or 0
            }
        }
    )


@router.get("/calculate-charge", response_class=JSONResponse)
async def get_charge(
    transaction_type: str,
    total: float,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    """Calculate charge breakdown from total amount entered"""
    actual_amount, charge, config = calculate_charge_from_total(db, transaction_type, total)

    return {
        "total": total,
        "amount": actual_amount,
        "charge": charge,  # This is the profit
        "charge_type": config.charge_type if config else None
    }


@router.post("/transaction")
async def create_transaction(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    """Create a new POS transaction"""
    body = await request.json()

    transaction_type = body.get("transaction_type")
    total = float(body.get("total", 0))
    customer_name = body.get("customer_name", "")
    customer_phone = body.get("customer_phone", "")
    notes = body.get("notes", "")

    if total <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than 0")

    # Calculate the actual amount and charge (profit) from the total
    actual_amount, charge, _ = calculate_charge_from_total(db, transaction_type, total)

    transaction = models.POSTransaction(
        user_id=user.id,
        transaction_type=transaction_type,
        amount=actual_amount,
        charge=charge,
        total=total,
        customer_name=customer_name,
        customer_phone=customer_phone,
        notes=notes
    )
    db.add(transaction)
    db.commit()

    return {
        "success": True,
        "transaction_id": transaction.id,
        "amount": actual_amount,
        "charge": charge,
        "total": total
    }


@router.get("/history", response_class=HTMLResponse)
async def transaction_history(
    request: Request,
    start_date: str = None,
    end_date: str = None,
    transaction_type: str = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    """View transaction history"""
    if not end_date:
        end_date = date.today().isoformat()
    if not start_date:
        start_date = (date.today() - timedelta(days=7)).isoformat()

    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()

    query = db.query(models.POSTransaction).filter(
        func.date(models.POSTransaction.created_at) >= start,
        func.date(models.POSTransaction.created_at) <= end
    )

    if transaction_type:
        query = query.filter(models.POSTransaction.transaction_type == transaction_type)

    transactions = query.order_by(models.POSTransaction.created_at.desc()).all()

    # Summary
    summary = db.query(
        func.sum(case((models.POSTransaction.transaction_type == 'withdrawal', models.POSTransaction.amount), else_=0)).label("total_withdrawals"),
        func.sum(case((models.POSTransaction.transaction_type == 'deposit', models.POSTransaction.amount), else_=0)).label("total_deposits"),
        func.sum(case((models.POSTransaction.transaction_type == 'withdrawal', models.POSTransaction.charge), else_=0)).label("withdrawal_charges"),
        func.sum(case((models.POSTransaction.transaction_type == 'deposit', models.POSTransaction.charge), else_=0)).label("deposit_charges")
    ).filter(
        func.date(models.POSTransaction.created_at) >= start,
        func.date(models.POSTransaction.created_at) <= end
    )

    if transaction_type:
        summary = summary.filter(models.POSTransaction.transaction_type == transaction_type)

    summary = summary.first()

    return templates.TemplateResponse(
        request, "pos_banking/history.html", {"user": user,
            "is_admin": user.role == "admin",
            "transactions": transactions,
            "start_date": start_date,
            "end_date": end_date,
            "selected_type": transaction_type,
            "summary": {
                "total_withdrawals": summary.total_withdrawals or 0,
                "total_deposits": summary.total_deposits or 0,
                "withdrawal_charges": summary.withdrawal_charges or 0,
                "deposit_charges": summary.deposit_charges or 0
            }
        }
    )


# Charge Configuration (Admin Only)
@router.get("/config", response_class=HTMLResponse)
async def charge_config_page(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    """Charge configuration page"""
    configs = db.query(models.POSChargeConfig).order_by(
        models.POSChargeConfig.transaction_type,
        models.POSChargeConfig.min_amount
    ).all()

    return templates.TemplateResponse(
        request, "pos_banking/config.html", {"user": user,
            "is_admin": True,
            "configs": configs
        }
    )


@router.post("/config/add")
async def add_charge_config(
    request: Request,
    transaction_type: str = Form(...),
    min_amount: float = Form(...),
    max_amount: float = Form(...),
    charge_type: str = Form(...),
    charge_value: float = Form(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    """Add a new charge configuration"""
    config = models.POSChargeConfig(
        transaction_type=transaction_type,
        min_amount=min_amount,
        max_amount=max_amount,
        charge_type=charge_type,
        charge_value=charge_value
    )
    db.add(config)
    db.commit()

    return RedirectResponse(url="/pos-banking/config", status_code=302)


@router.post("/config/{config_id}/update")
async def update_charge_config(
    config_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    """Update a charge configuration"""
    body = await request.json()

    config = db.query(models.POSChargeConfig).filter(
        models.POSChargeConfig.id == config_id
    ).first()

    if not config:
        raise HTTPException(status_code=404, detail="Config not found")

    config.min_amount = body.get("min_amount", config.min_amount)
    config.max_amount = body.get("max_amount", config.max_amount)
    config.charge_type = body.get("charge_type", config.charge_type)
    config.charge_value = body.get("charge_value", config.charge_value)
    config.is_active = body.get("is_active", config.is_active)

    db.commit()

    return {"success": True}


@router.post("/config/{config_id}/delete")
async def delete_charge_config(
    config_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    """Delete a charge configuration"""
    config = db.query(models.POSChargeConfig).filter(
        models.POSChargeConfig.id == config_id
    ).first()

    if config:
        db.delete(config)
        db.commit()

    return RedirectResponse(url="/pos-banking/config", status_code=302)


@router.post("/transaction/{transaction_id}/delete")
async def delete_transaction(
    transaction_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    """Delete a POS transaction (admin only)"""
    transaction = db.query(models.POSTransaction).filter(
        models.POSTransaction.id == transaction_id
    ).first()

    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    db.delete(transaction)
    db.commit()

    return {"success": True, "message": "Transaction deleted"}
