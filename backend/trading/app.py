from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import asyncio
import os
from datetime import datetime

# ============================================================
# DATABASE
# ============================================================

from database import Base, engine, get_db_session
from database.models import User, Portfolio, Trade, Strategy

# ============================================================
# STOCK SERVICE
# ============================================================
from trading.stock_service import stock_service


# ============================================================
# PATHS
# ============================================================

# app.py:
# D:\TradingApp\backend\trading\app.py
#
# Project root:
# D:\TradingApp
#
# Frontend:
# D:\TradingApp\frontend

BASE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)

FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")


# ============================================================
# WEBSOCKET CONNECTION MANAGEMENT
# ============================================================

active_connections = []


# ============================================================
# BACKGROUND WORKER
# ============================================================

async def auto_trading_worker():
    """
    Background worker for automatic trading.

    This currently acts as a placeholder.
    Strategy execution logic can be added here later.
    """

    while True:
        try:
            # Automatic trading logic will go here.
            await asyncio.sleep(10)

        except asyncio.CancelledError:
            print("Auto trading worker stopped.")
            break

        except Exception as e:
            print(f"Error in auto trading worker: {e}")
            await asyncio.sleep(10)


# ============================================================
# APPLICATION LIFESPAN
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):

    # --------------------------------------------------------
    # Initialize database
    # --------------------------------------------------------

    print("Initializing database...")

    try:
        Base.metadata.create_all(bind=engine)
        print("Database initialized successfully.")

    except Exception as e:
        print(f"Database initialization error: {e}")

    # --------------------------------------------------------
    # Start background worker
    # --------------------------------------------------------

    background_task = asyncio.create_task(
        auto_trading_worker()
    )

    print("Auto trading worker started.")

    yield

    # --------------------------------------------------------
    # Shutdown
    # --------------------------------------------------------

    print("Shutting down application...")

    background_task.cancel()

    try:
        await background_task
    except asyncio.CancelledError:
        pass

    # Close WebSocket connections

    for connection in active_connections.copy():

        try:
            await connection.close()

        except Exception:
            pass

    active_connections.clear()

    print("Application shutdown complete.")


# ============================================================
# FASTAPI APPLICATION
# ============================================================

app = FastAPI(
    title="Trading App API",
    description="Trading application with automatic buying and selling",
    version="1.0.0",
    lifespan=lifespan
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127[.]0[.]0[.]1)(:[0-9]+)?$",
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://learningtrading-1.onrender.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# FRONTEND
# ============================================================

@app.get("/")
async def root():

    index_path = os.path.join(
        FRONTEND_DIR,
        "index.html"
    )

    if os.path.exists(index_path):
        return FileResponse(
            path=index_path,
            media_type="text/html"
        )

    return {
        "status": "success",
        "message": "Trading App API is running",
        "frontend": "index.html not found"
    }


# ============================================================
# WEBSOCKET
# ============================================================

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    client_id: int
):

    await websocket.accept()

    active_connections.append(websocket)

    print(
        f"WebSocket client {client_id} connected."
    )

    try:

        while True:

            data = await websocket.receive_text()

            # Broadcast to all other connections

            for connection in active_connections.copy():

                if connection != websocket:

                    try:
                        await connection.send_text(data)

                    except Exception:
                        pass

    except WebSocketDisconnect:

        if websocket in active_connections:
            active_connections.remove(websocket)

        print(
            f"WebSocket client {client_id} disconnected."
        )

    except Exception as e:

        print(
            f"WebSocket error for client {client_id}: {e}"
        )

        if websocket in active_connections:
            active_connections.remove(websocket)


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
async def health_check():

    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    }


# ============================================================
# STOCK PRICE
# ============================================================

@app.get("/api/stock/{symbol}")
async def get_stock_price(symbol: str):

    """
    Get current stock price.
    """

    data = stock_service.get_stock_price(
        symbol.upper()
    )

    if data:

        return {
            "status": "success",
            "data": data
        }

    return {
        "status": "error",
        "message": f"Could not fetch data for {symbol}"
    }


# ============================================================
# STOCK PRICE - FRONTEND COMPATIBILITY
# ============================================================

@app.get("/api/stock/{symbol}/price")
async def get_stock_price_compatibility(symbol: str):

    """
    Compatibility endpoint used by the frontend.

    The frontend calls:

        /api/stock/AAPL/price
    """

    data = stock_service.get_stock_price(
        symbol.upper()
    )

    if data:

        return {
            "status": "success",
            "symbol": data.get("symbol", symbol.upper()),
            "price": data.get("current_price", 0),
            "change": data.get("change", 0),
            "change_percent": data.get(
                "change_percent",
                "0%"
            ),
            "high": data.get("high", 0),
            "low": data.get("low", 0),
            "open": data.get("open", 0),
            "previous_close": data.get(
                "previous_close",
                0
            ),
            "volume": data.get("volume", 0)
        }

    return {
        "status": "error",
        "message": f"Could not fetch data for {symbol}"
    }


# ============================================================
# MULTIPLE STOCK PRICES
# ============================================================

@app.get("/api/stocks/")
async def get_multiple_stocks(
    symbols: str
):

    """
    Get prices for multiple stocks.

    Example:

        /api/stocks/?symbols=AAPL,MSFT,NVDA
    """

    symbol_list = [
        symbol.strip().upper()
        for symbol in symbols.split(",")
        if symbol.strip()
    ]

    results = stock_service.get_multiple_prices(
        symbol_list
    )

    return {
        "status": "success",
        "data": results
    }


@app.get("/api/stocks/search")
async def search_stock_assets(q: str, limit: int = 8):
    """Search active US equity tickers and company names for autocomplete."""

    try:
        results = stock_service.search_stock_assets(q, limit)
        return {
            "status": "success",
            "query": q,
            "results": results
        }
    except Exception as error:
        print(f"Stock asset search error: {error}")
        return {
            "status": "error",
            "query": q,
            "results": [],
            "message": "Stock search is temporarily unavailable."
        }


# ============================================================
# HISTORICAL STOCK DATA
# ============================================================

@app.get("/api/stock/{symbol}/history")
async def get_stock_history(
    symbol: str,
    period: str = "1mo",
    interval: str = "1d"
):

    """
    Get historical stock data.

    Example:

        /api/stock/AAPL/history?period=3mo&interval=1d
    """

    try:

        data = stock_service.get_historical_data(
            symbol.upper(),
            period,
            interval
        )

        if data:

            return {
                "status": "success",
                "symbol": symbol.upper(),
                "period": period,
                "interval": interval,
                "data": data
            }

        return {
            "status": "error",
            "message": f"No historical data found for {symbol}"
        }

    except Exception as e:

        print(
            f"Historical data error for {symbol}: {e}"
        )

        return {
            "status": "error",
            "message": str(e)
        }


# ============================================================
# COMPARATIVE ANALYSIS
# ============================================================

@app.get("/api/stock/{symbol}/analysis")
async def get_market_analysis(
    symbol: str,
    benchmark: str = "SPY",
    sector: str = "XLK",
    period: str = "3mo"
):
    """Return descriptive volatility, momentum, and correlation metrics."""

    try:
        return stock_service.get_market_analysis(
            symbol.upper(),
            benchmark.upper(),
            sector.upper(),
            period
        )
    except Exception as e:
        print(f"Market analysis error for {symbol}: {e}")
        return {
            "status": "error",
            "message": str(e)
        }


@app.get("/api/stock/{symbol}/historical-evaluation")
async def get_historical_evaluation(
    symbol: str,
    strategy: str,
    cutoff_date: str,
    horizon_days: int = 10,
    period: str = "3mo"
):
    """Evaluate a strategy using only data available at a historical cutoff."""

    try:
        return stock_service.evaluate_historical_prediction(
            symbol.upper(),
            strategy,
            cutoff_date,
            horizon_days,
            period
        )
    except Exception as e:
        print(f"Historical evaluation error for {symbol}: {e}")
        return {"status": "error", "message": str(e)}


# ============================================================
# STRATEGY DATA
# ============================================================

@app.get("/api/stock/{symbol}/strategy/{strategy}")
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
        ?period=3mo&interval=1d
    """

    try:

        strategy_data = stock_service.get_strategy_signals(
            symbol=symbol.upper(),
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

@app.get("/api/portfolio/{user_id}")
async def get_portfolio(
    user_id: int
):

    db = next(get_db_session())

    try:

        portfolio = (
            db.query(Portfolio)
            .filter(
                Portfolio.user_id == user_id
            )
            .first()
        )

        if not portfolio:

            portfolio = Portfolio(
                user_id=user_id,
                cash=100000.0,
                total_value=100000.0
            )

            db.add(portfolio)
            db.commit()
            db.refresh(portfolio)

        return portfolio

    finally:

        db.close()


# ============================================================
# EXECUTE TRADE
# ============================================================

@app.post("/api/portfolio/{user_id}/trade")
async def execute_trade(
    user_id: int,
    trade_data: dict
):

    db = next(get_db_session())

    try:

        portfolio = (
            db.query(Portfolio)
            .filter(
                Portfolio.user_id == user_id
            )
            .first()
        )

        if not portfolio:

            portfolio = Portfolio(
                user_id=user_id,
                cash=100000.0,
                total_value=100000.0
            )

            db.add(portfolio)
            db.commit()
            db.refresh(portfolio)

        # ----------------------------------------------------
        # Extract trade data
        # ----------------------------------------------------

        symbol = trade_data.get("symbol")
        side = trade_data.get("side")
        quantity = trade_data.get("quantity")
        price = trade_data.get("price")

        # ----------------------------------------------------
        # Validate
        # ----------------------------------------------------

        if not symbol:

            return {
                "status": "error",
                "message": "Symbol is required"
            }

        if side not in ["buy", "sell"]:

            return {
                "status": "error",
                "message": "Invalid trade side"
            }

        if quantity is None or quantity <= 0:

            return {
                "status": "error",
                "message": "Quantity must be greater than zero"
            }

        if price is None or price <= 0:

            return {
                "status": "error",
                "message": "Price must be greater than zero"
            }

        # ----------------------------------------------------
        # Calculate total
        # ----------------------------------------------------

        total_amount = quantity * price

        # ----------------------------------------------------
        # BUY
        # ----------------------------------------------------

        if side == "buy":

            if portfolio.cash < total_amount:

                return {
                    "status": "error",
                    "message": "Insufficient funds"
                }

            portfolio.cash -= total_amount

            portfolio.total_value = (
                portfolio.cash +
                total_amount
            )

            trade = Trade(
                portfolio_id=portfolio.id,
                symbol=symbol.upper(),
                side=side,
                quantity=quantity,
                price=price,
                total_amount=total_amount
            )

            db.add(trade)
            db.commit()

            return {
                "status": "success",
                "message": "Buy order executed",
                "symbol": symbol.upper(),
                "quantity": quantity,
                "price": price,
                "total_amount": total_amount
            }

        # ----------------------------------------------------
        # SELL
        # ----------------------------------------------------

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
                "message": "Sell order executed",
                "symbol": symbol.upper(),
                "quantity": quantity,
                "price": price,
                "total_amount": total_amount
            }

    except Exception as e:

        db.rollback()

        print(
            f"Trade execution error: {e}"
        )

        return {
            "status": "error",
            "message": str(e)
        }

    finally:

        db.close()


# ============================================================
# TRADE HISTORY
# ============================================================

@app.get("/api/trades/{user_id}")
async def get_trades(
    user_id: int
):

    db = next(get_db_session())

    try:

        portfolio = (
            db.query(Portfolio)
            .filter(
                Portfolio.user_id == user_id
            )
            .first()
        )

        if not portfolio:
            return []

        trades = (
            db.query(Trade)
            .filter(
                Trade.portfolio_id == portfolio.id
            )
            .order_by(
                Trade.timestamp.desc()
            )
            .all()
        )

        return [
            {
                "id": trade.id,
                "symbol": trade.symbol,
                "side": trade.side,
                "quantity": trade.quantity,
                "price": trade.price,
                "total_amount": trade.total_amount,
                "timestamp": (
                    trade.timestamp.isoformat()
                    if trade.timestamp
                    else None
                )
            }
            for trade in trades
        ]

    finally:

        db.close()


# ============================================================
# FRONTEND STATIC FILES
# ============================================================

@app.get("/{filename}")
async def serve_frontend(
    filename: str
):

    file_path = os.path.join(
        FRONTEND_DIR,
        filename
    )

    if os.path.exists(file_path):

        return FileResponse(
            path=file_path
        )

    index_path = os.path.join(
        FRONTEND_DIR,
        "index.html"
    )

    if os.path.exists(index_path):

        return FileResponse(
            path=index_path,
            media_type="text/html"
        )

    return {
        "status": "error",
        "message": "Frontend file not found"
    }


# ============================================================
# RUN DIRECTLY
# ============================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )