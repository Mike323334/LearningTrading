from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from database import get_db_session, init_db
from models import User, Trade, Portfolio, Strategy
from stock_service import stock_service
from typing import List


router = APIRouter(prefix="/api", tags=["trading"])


# ============================================================
# STOCK PRICE
# ============================================================

@router.get("/stock/{symbol}/price")
async def get_stock_price(symbol: str):
    """Get current stock price from Alpaca."""
    
    price_data = stock_service.get_stock_price(symbol)

    if price_data:
        return {
            "status": "success",
            "symbol": price_data["symbol"],
            "price": price_data["current_price"],
            "change": price_data.get("change", 0),
            "change_percent": price_data.get("change_percent", "0%"),
            "high": price_data["high"],
            "low": price_data["low"],
            "open": price_data["open"],
            "previous_close": price_data["previous_close"],
            "volume": price_data["volume"]
        }

    return {
        "status": "error",
        "message": "Failed to fetch stock price"
    }


# ============================================================
# HISTORICAL STOCK DATA
# ============================================================

@router.get("/stock/{symbol}/history")
async def get_stock_history(
    symbol: str,
    period: str = "5d",
    interval: str = "1d"
):
    """Get historical stock data from Alpaca."""

    try:
        history_data = stock_service.get_historical_data(
            symbol,
            period,
            interval
        )

        if history_data:
            return {
                "status": "success",
                "symbol": symbol.upper(),
                "period": period,
                "interval": interval,
                "data": history_data
            }

        return {
            "status": "error",
            "message": "Failed to fetch historical data"
        }

    except Exception as e:
        print(f"Error getting historical data: {e}")

        return {
            "status": "error",
            "message": str(e)
        }


# ============================================================
# STRATEGY DATA / INDICATORS / SIGNALS
# ============================================================

@router.get("/stock/{symbol}/strategy/{strategy}")
async def get_strategy_data(
    symbol: str,
    strategy: str,
    period: str = "3mo",
    interval: str = "1d"
):
    """
    Calculate trading strategy indicators and signals.

    Example:
    /api/stock/AAPL/strategy/moving_average_crossover
    """

    try:
        strategy_data = stock_service.get_strategy_signals(
            symbol=symbol,
            strategy=strategy,
            period=period,
            interval=interval
        )

        if strategy_data is None:
            return {
                "status": "error",
                "message": "Failed to calculate strategy"
            }

        return {
            "status": "success",
            "symbol": symbol.upper(),
            "strategy": strategy,
            "period": period,
            "interval": interval,
            "data": strategy_data
        }

    except Exception as e:
        print(
            f"Error calculating strategy "
            f"{strategy} for {symbol}: {e}"
        )

        return {
            "status": "error",
            "message": str(e)
        }


# ============================================================
# PORTFOLIO
# ============================================================

@router.get("/portfolio/{user_id}")
async def get_portfolio(
    user_id: int,
    db: Session = Depends(get_db_session)
):
    """Get user portfolio."""

    portfolio = (
        db.query(Portfolio)
        .filter(Portfolio.user_id == user_id)
        .first()
    )

    return portfolio


# ============================================================
# EXECUTE TRADE
# ============================================================

@router.post("/portfolio/{user_id}/trade")
async def execute_trade(
    user_id: int,
    symbol: str,
    side: str,
    quantity: int,
    price: float,
    db: Session = Depends(get_db_session)
):
    """Execute a trade."""

    # Get or create portfolio
    portfolio = (
        db.query(Portfolio)
        .filter(Portfolio.user_id == user_id)
        .first()
    )

    if not portfolio:
        portfolio = Portfolio(
            user_id=user_id,
            cash=100000.0
        )

        db.add(portfolio)
        db.commit()
        db.refresh(portfolio)

    # Calculate trade amount
    total_amount = quantity * price

    # ========================================================
    # BUY
    # ========================================================

    if side == "buy":

        if portfolio.cash >= total_amount:

            portfolio.cash -= total_amount

            trade = Trade(
                portfolio_id=portfolio.id,
                symbol=symbol.upper(),
                side=side,
                quantity=quantity,
                price=price,
                total_amount=total_amount
            )

            db.add(trade)

            portfolio.total_value = (
                portfolio.cash +
                (quantity * price)
            )

            db.commit()

            return {
                "status": "success",
                "message": "Buy order executed"
            }

        else:

            return {
                "status": "error",
                "message": "Insufficient funds"
            }

    # ========================================================
    # SELL
    # ========================================================

    elif side == "sell":

        trade = Trade(
            portfolio_id=portfolio.id,
            symbol=symbol.upper(),
            side=side,
            quantity=quantity,
            price=price,
            total_amount=total_amount
        )

        db.add(trade)

        portfolio.cash += total_amount
        portfolio.total_value = portfolio.cash

        db.commit()

        return {
            "status": "success",
            "message": "Sell order executed"
        }

    # ========================================================
    # INVALID SIDE
    # ========================================================

    return {
        "status": "error",
        "message": "Invalid trade side"
    }


# ============================================================
# TRADE HISTORY
# ============================================================

@router.get("/trades/{user_id}")
async def get_trades(
    user_id: int,
    db: Session = Depends(get_db_session)
):
    """Get trade history for user."""

    trades = (
        db.query(Trade)
        .filter(
            Trade.portfolio.has(user_id=user_id)
        )
        .all()
    )

    return trades


# ============================================================
# CREATE STRATEGY
# ============================================================

@router.post("/strategies/")
async def create_strategy(
    name: str,
    description: str = "",
    db: Session = Depends(get_db_session)
):
    """Create a new trading strategy."""

    strategy = Strategy(
        name=name,
        description=description
    )

    db.add(strategy)
    db.commit()
    db.refresh(strategy)

    return strategy


# ============================================================
# GET STRATEGY
# ============================================================

@router.get("/strategies/{strategy_id}")
async def get_strategy(
    strategy_id: int,
    db: Session = Depends(get_db_session)
):
    """Get strategy details."""

    strategy = (
        db.query(Strategy)
        .filter(Strategy.id == strategy_id)
        .first()
    )

    return strategy