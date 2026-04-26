from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from datetime import datetime, date, timedelta
from .. import models, auth
from ..database import get_db
from ..config import settings

router = APIRouter(prefix="/balance", tags=["balance"])
templates = Jinja2Templates(directory=settings.TEMPLATES_DIR)


def get_balance_summary(db: Session, target_date: date = None):
    """Calculate cash and POS balance for a given date"""
    if target_date is None:
        target_date = date.today()

    yesterday = target_date - timedelta(days=1)
    yesterday_str = yesterday.isoformat()

    # Get previous day's carryover
    yesterday_carryover = db.query(models.DailyCarryover).filter(
        models.DailyCarryover.date == yesterday_str
    ).first()

    prev_cash_carryover = yesterday_carryover.cash_carryover if yesterday_carryover else 0
    prev_pos_carryover = yesterday_carryover.pos_carryover if yesterday_carryover else 0

    # Get today's sales by payment method
    sales_by_method = db.query(
        func.sum(case((models.Sale.payment_method == 'cash', models.Sale.total_amount), else_=0)).label("cash_sales"),
        func.sum(case((models.Sale.payment_method == 'pos', models.Sale.total_amount), else_=0)).label("pos_sales"),
        func.sum(case((models.Sale.payment_method == 'split', models.Sale.cash_amount), else_=0)).label("split_cash"),
        func.sum(case((models.Sale.payment_method == 'split', models.Sale.pos_amount), else_=0)).label("split_pos")
    ).filter(
        func.date(models.Sale.created_at) == target_date
    ).first()

    cash_sales = (sales_by_method.cash_sales or 0) + (sales_by_method.split_cash or 0) if sales_by_method else 0
    pos_sales = (sales_by_method.pos_sales or 0) + (sales_by_method.split_pos or 0) if sales_by_method else 0

    # Get POS banking transactions
    pos_banking = db.query(
        func.sum(case((models.POSTransaction.transaction_type == 'withdrawal', models.POSTransaction.total), else_=0)).label("withdrawal_total"),
        func.sum(case((models.POSTransaction.transaction_type == 'withdrawal', models.POSTransaction.amount), else_=0)).label("withdrawal_amount"),
        func.sum(case((models.POSTransaction.transaction_type == 'deposit', models.POSTransaction.total), else_=0)).label("deposit_total"),
        func.sum(case((models.POSTransaction.transaction_type == 'deposit', models.POSTransaction.amount), else_=0)).label("deposit_amount")
    ).filter(
        func.date(models.POSTransaction.created_at) == target_date
    ).first()

    withdrawal_total = pos_banking.withdrawal_total or 0 if pos_banking else 0
    withdrawal_amount = pos_banking.withdrawal_amount or 0 if pos_banking else 0
    deposit_total = pos_banking.deposit_total or 0 if pos_banking else 0
    deposit_amount = pos_banking.deposit_amount or 0 if pos_banking else 0

    # Get balance withdrawals
    balance_withdrawals = db.query(
        func.sum(case((models.BalanceWithdrawal.withdrawal_type == 'cash', models.BalanceWithdrawal.amount), else_=0)).label("cash_withdrawals"),
        func.sum(case((models.BalanceWithdrawal.withdrawal_type == 'pos', models.BalanceWithdrawal.amount), else_=0)).label("pos_withdrawals")
    ).filter(
        func.date(models.BalanceWithdrawal.created_at) == target_date
    ).first()

    cash_withdrawals = balance_withdrawals.cash_withdrawals or 0 if balance_withdrawals else 0
    pos_withdrawals = balance_withdrawals.pos_withdrawals or 0 if balance_withdrawals else 0

    # Get POS cashback (cash given out from POS payments)
    pos_cashback_total = db.query(
        func.sum(models.Sale.pos_cashback)
    ).filter(
        func.date(models.Sale.created_at) == target_date,
        models.Sale.pos_cashback > 0
    ).scalar() or 0

    # Calculate POS fee
    pos_fee_setting = db.query(models.SystemSettings).filter(
        models.SystemSettings.key == "pos_fee_percentage"
    ).first()
    pos_fee_cap_setting = db.query(models.SystemSettings).filter(
        models.SystemSettings.key == "pos_fee_cap"
    ).first()
    pos_fee_percentage = float(pos_fee_setting.value) if pos_fee_setting else 0
    pos_fee_cap = float(pos_fee_cap_setting.value) if pos_fee_cap_setting else 100

    # Get individual POS sales for fee calculation
    pos_sales_list = db.query(models.Sale.total_amount, models.Sale.pos_amount, models.Sale.payment_method).filter(
        func.date(models.Sale.created_at) == target_date,
        models.Sale.payment_method.in_(['pos', 'split'])
    ).all()

    pos_fee = sum(
        min((sale.total_amount if sale.payment_method == 'pos' else sale.pos_amount) * (pos_fee_percentage / 100), pos_fee_cap)
        for sale in pos_sales_list
    ) if pos_fee_percentage > 0 else 0

    # Calculate balances
    # Cash: Carryover + Cash Sales + Deposits (cash in) - Withdrawals (cash out) - Balance Withdrawals - POS Cashback (cash given out)
    cash_balance = prev_cash_carryover + cash_sales + deposit_total - withdrawal_amount - cash_withdrawals - pos_cashback_total
    pos_balance = prev_pos_carryover + pos_sales - pos_fee + withdrawal_total - deposit_amount - pos_withdrawals

    return {
        "cash_balance": cash_balance,
        "pos_balance": pos_balance,
        "prev_cash_carryover": prev_cash_carryover,
        "prev_pos_carryover": prev_pos_carryover,
        "cash_sales": cash_sales,
        "pos_sales": pos_sales,
        "pos_fee": pos_fee,
        "withdrawal_total": withdrawal_total,
        "withdrawal_amount": withdrawal_amount,
        "deposit_total": deposit_total,
        "deposit_amount": deposit_amount,
        "cash_withdrawals": cash_withdrawals,
        "pos_withdrawals": pos_withdrawals,
        "pos_cashback_total": pos_cashback_total
    }


@router.get("", response_class=HTMLResponse)
async def balance_page(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    """Balance withdrawal page"""
    today = date.today()
    summary = get_balance_summary(db, today)

    # Get today's withdrawals
    withdrawals = db.query(models.BalanceWithdrawal).filter(
        func.date(models.BalanceWithdrawal.created_at) == today
    ).order_by(models.BalanceWithdrawal.created_at.desc()).all()

    return templates.TemplateResponse(
        request, "balance/index.html", {
            "user": user,
            "is_admin": user.role == "admin",
            "summary": summary,
            "withdrawals": withdrawals
        }
    )


@router.get("/summary", response_class=JSONResponse)
async def get_balance(
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    """Get current balance summary"""
    summary = get_balance_summary(db)
    return summary


@router.post("/withdraw")
async def create_withdrawal(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    """Create a balance withdrawal"""
    body = await request.json()

    withdrawal_type = body.get("withdrawal_type")  # "cash" or "pos"
    amount = float(body.get("amount", 0))
    reason = body.get("reason", "")

    if withdrawal_type not in ["cash", "pos"]:
        raise HTTPException(status_code=400, detail="Invalid withdrawal type")

    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than 0")

    # Check if sufficient balance
    summary = get_balance_summary(db)
    if withdrawal_type == "cash" and amount > summary["cash_balance"]:
        raise HTTPException(status_code=400, detail=f"Insufficient cash balance. Available: N{summary['cash_balance']:,.0f}")
    if withdrawal_type == "pos" and amount > summary["pos_balance"]:
        raise HTTPException(status_code=400, detail=f"Insufficient POS balance. Available: N{summary['pos_balance']:,.0f}")

    withdrawal = models.BalanceWithdrawal(
        user_id=user.id,
        withdrawal_type=withdrawal_type,
        amount=amount,
        reason=reason
    )
    db.add(withdrawal)
    db.commit()

    # Get updated balance
    updated_summary = get_balance_summary(db)

    return {
        "success": True,
        "withdrawal_id": withdrawal.id,
        "amount": amount,
        "withdrawal_type": withdrawal_type,
        "new_cash_balance": updated_summary["cash_balance"],
        "new_pos_balance": updated_summary["pos_balance"]
    }


@router.post("/withdraw/{withdrawal_id}/delete")
async def delete_withdrawal(
    withdrawal_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_admin)
):
    """Delete a withdrawal (admin only)"""
    withdrawal = db.query(models.BalanceWithdrawal).filter(
        models.BalanceWithdrawal.id == withdrawal_id
    ).first()

    if not withdrawal:
        raise HTTPException(status_code=404, detail="Withdrawal not found")

    db.delete(withdrawal)
    db.commit()

    return {"success": True, "message": "Withdrawal deleted"}


@router.get("/history", response_class=HTMLResponse)
async def withdrawal_history(
    request: Request,
    start_date: str = None,
    end_date: str = None,
    withdrawal_type: str = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_login)
):
    """View withdrawal history"""
    if not end_date:
        end_date = date.today().isoformat()
    if not start_date:
        start_date = (date.today() - timedelta(days=7)).isoformat()

    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()

    query = db.query(models.BalanceWithdrawal).filter(
        func.date(models.BalanceWithdrawal.created_at) >= start,
        func.date(models.BalanceWithdrawal.created_at) <= end
    )

    if withdrawal_type:
        query = query.filter(models.BalanceWithdrawal.withdrawal_type == withdrawal_type)

    withdrawals = query.order_by(models.BalanceWithdrawal.created_at.desc()).all()

    # Summary
    summary = db.query(
        func.sum(case((models.BalanceWithdrawal.withdrawal_type == 'cash', models.BalanceWithdrawal.amount), else_=0)).label("total_cash"),
        func.sum(case((models.BalanceWithdrawal.withdrawal_type == 'pos', models.BalanceWithdrawal.amount), else_=0)).label("total_pos"),
        func.count(case((models.BalanceWithdrawal.withdrawal_type == 'cash', 1), else_=None)).label("cash_count"),
        func.count(case((models.BalanceWithdrawal.withdrawal_type == 'pos', 1), else_=None)).label("pos_count")
    ).filter(
        func.date(models.BalanceWithdrawal.created_at) >= start,
        func.date(models.BalanceWithdrawal.created_at) <= end
    )

    if withdrawal_type:
        summary = summary.filter(models.BalanceWithdrawal.withdrawal_type == withdrawal_type)

    summary = summary.first()

    return templates.TemplateResponse(
        request, "balance/history.html", {
            "user": user,
            "is_admin": user.role == "admin",
            "withdrawals": withdrawals,
            "start_date": start_date,
            "end_date": end_date,
            "selected_type": withdrawal_type,
            "summary": {
                "total_cash": summary.total_cash or 0,
                "total_pos": summary.total_pos or 0,
                "cash_count": summary.cash_count or 0,
                "pos_count": summary.pos_count or 0
            }
        }
    )
