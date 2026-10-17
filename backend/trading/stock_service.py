import requests
from datetime import datetime, timedelta, timezone
import time
import math

from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, FRED_API_KEY, SEC_USER_AGENT


class StockService:
    """
    Stock data service backed by Alpaca's Market Data API.

    The strategy methods in this service provide PRELIMINARY market analysis.
    They do not execute trades.

    The frontend can use the returned analysis to:
        1. Display indicators on the chart.
        2. Display a preliminary BUY / SELL / NEUTRAL signal.
        3. Explain why the signal was generated.
        4. Let the user decide whether to execute a trade.
    """

    def __init__(self):
        self.cache = {}
        self.cache_timeout = 30

        self.api_key = ALPACA_API_KEY
        self.secret_key = ALPACA_SECRET_KEY

        self.base_url = "https://data.alpaca.markets/v2"
        self.trading_base_url = "https://paper-api.alpaca.markets/v2"

        self.headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key
        }

        # Alpaca free-tier market data feed.
        self.feed = "iex"
        self.sec_cache = {}
        self.news_cache = {}
        self.macro_cache = None
        self.asset_directory_cache = []
        self.asset_directory_cache_timestamp = 0
        self.sec_cik_map = {
            "AAPL": "0000320193",
            "MSFT": "0000789019",
            "GOOGL": "0001652044",
            "AMZN": "0001018724",
            "NVDA": "0001045810",
            "TSLA": "0001318605",
            "META": "0001326801"
        }

    # -----------------------------------------------------------------
    # Utility helpers
    # -----------------------------------------------------------------

    @staticmethod
    def _clean_number(value, digits=4):
        """
        Convert a numeric value to a JSON-safe number.

        Pandas can produce NaN, which is not desirable in JSON responses.
        """
        if value is None:
            return None

        try:
            value = float(value)

            if math.isnan(value) or math.isinf(value):
                return None

            return round(value, digits)

        except (TypeError, ValueError):
            return None

    @staticmethod
    def _series_to_list(series, digits=4):
        """
        Convert a Pandas Series to a JSON-safe list.
        """
        return [
            StockService._clean_number(value, digits)
            for value in series.tolist()
        ]

    @staticmethod
    def _signal_strength(signal_count, latest_signal):
        """
        Preliminary signal strength.

        This is intentionally conservative. It is not a probability
        and should not be interpreted as a guaranteed prediction.
        """
        if latest_signal == "neutral":
            return "low"

        if signal_count >= 3:
            return "strong"

        if signal_count >= 1:
            return "medium"

        return "low"

    @staticmethod
    def _build_base_analysis(
        strategy,
        signal,
        strength,
        current_price,
        reasoning,
        risk_notes
    ):
        """
        Standard structure returned to the frontend.
        """
        return {
            "strategy": strategy,
            "signal": signal,
            "strength": strength,
            "current_price": StockService._clean_number(current_price, 2),
            "reasoning": reasoning,
            "risk_notes": risk_notes
        }

    # -----------------------------------------------------------------
    # Current price
    # -----------------------------------------------------------------

    def get_stock_price(self, symbol: str):
        """Get current stock price using Alpaca's snapshot endpoint."""

        cache_key = symbol.upper()
        current_time = time.time()

        if cache_key in self.cache:
            cached_data = self.cache[cache_key]

            if current_time - cached_data["timestamp"] < self.cache_timeout:
                return cached_data["data"]

        try:
            url = f"{self.base_url}/stocks/{cache_key}/snapshot"

            params = {
                "feed": self.feed
            }

            response = requests.get(
                url,
                headers=self.headers,
                params=params,
                timeout=10
            )

            response.raise_for_status()

            data = response.json()

            latest_trade = data.get("latestTrade") or {}
            daily_bar = data.get("dailyBar") or {}
            prev_bar = data.get("prevDailyBar") or {}

            current_price = latest_trade.get("p") or daily_bar.get("c")
            previous_close = prev_bar.get("c", 0)

            if not current_price:
                note = data.get("message") or data.get("error")

                print(
                    f"No snapshot data returned for {symbol} "
                    f"from Alpaca: {note or data}"
                )

                return self._get_mock_price(symbol)

            change = (
                current_price - previous_close
                if previous_close
                else 0
            )

            change_percent = (
                change / previous_close * 100
                if previous_close
                else 0
            )

            price_data = {
                "symbol": cache_key,
                "current_price": float(current_price),
                "previous_close": float(previous_close),
                "open": float(daily_bar.get("o", 0)),
                "high": float(daily_bar.get("h", 0)),
                "low": float(daily_bar.get("l", 0)),
                "volume": int(daily_bar.get("v", 0)),
                "change": round(change, 2),
                "change_percent": f"{change_percent:.2f}%",
                "timestamp": current_time
            }

            self.cache[cache_key] = {
                "data": price_data,
                "timestamp": current_time
            }

            return price_data

        except Exception as e:
            print(f"Error fetching stock data for {symbol}: {e}")

            return self._get_mock_price(symbol)

    def search_stock_assets(self, query: str, limit: int = 8):
        """Search active, tradable US equity assets by ticker or company name."""

        normalized_query = query.strip().casefold()
        if len(normalized_query) < 2:
            return []

        if (
            not self.asset_directory_cache
            or time.time() - self.asset_directory_cache_timestamp > 3600
        ):
            try:
                response = requests.get(
                    f"{self.trading_base_url}/assets",
                    headers=self.headers,
                    params={
                        "status": "active",
                        "asset_class": "us_equity"
                    },
                    timeout=15
                )
                response.raise_for_status()
                assets = response.json()
                self.asset_directory_cache = [
                    {
                        "symbol": asset["symbol"],
                        "name": asset.get("name") or asset["symbol"],
                        "exchange": asset.get("exchange", ""),
                    }
                    for asset in assets
                    if asset.get("tradable")
                    and asset.get("status") == "active"
                    and asset.get("class") == "us_equity"
                    and asset.get("symbol")
                ]
                self.asset_directory_cache_timestamp = time.time()
            except Exception as error:
                print(f"Alpaca asset search error: {error}")
                return []

        matches = []
        for asset in self.asset_directory_cache:
            symbol = asset["symbol"].casefold()
            name = asset["name"].casefold()
            if normalized_query == symbol:
                rank = 0
            elif symbol.startswith(normalized_query):
                rank = 1
            elif name.startswith(normalized_query) and symbol.upper() in self.sec_cik_map:
                rank = 2
            elif name.startswith(normalized_query) and "common stock" in name:
                rank = 3
            elif name.startswith(normalized_query):
                rank = 4
            elif normalized_query in symbol:
                rank = 5
            elif "common stock" in name and normalized_query in name:
                rank = 6
            elif normalized_query in name:
                rank = 7
            else:
                continue
            matches.append((rank, asset))

        matches.sort(key=lambda item: (item[0], item[1]["symbol"]))
        return [asset for _, asset in matches[:max(1, min(limit, 20))]]

    # -----------------------------------------------------------------
    # Historical / intraday bars
    # -----------------------------------------------------------------

    def get_historical_data(
        self,
        symbol: str,
        period: str = "5d",
        interval: str = "1d",
        start_date=None,
        end_date=None
    ):
        """
        Get historical price data using Alpaca's bars endpoint.
        """

        timeframe_map = {
            "1m": "1Min",
            "5m": "5Min",
            "15m": "15Min",
            "30m": "30Min",
            "1h": "1Hour",
            "1d": "1Day"
        }

        timeframe = timeframe_map.get(interval, "1Day")

        period_days = {
            "1d": 1,
            "5d": 5,
            "1mo": 30,
            "3mo": 90,
            "6mo": 180,
            "1y": 365
        }

        days_back = period_days.get(period, 5)

        if end_date:
            end_dt = datetime.fromisoformat(
                str(end_date).replace("Z", "+00:00")
            ).replace(hour=23, minute=59, second=59, microsecond=0)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
        else:
            end_dt = datetime.now(timezone.utc)

        if start_date:
            start_dt = datetime.fromisoformat(
                str(start_date).replace("Z", "+00:00")
            )
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
        else:
            start_dt = end_dt - timedelta(days=days_back + 4)

        try:
            url = f"{self.base_url}/stocks/{symbol.upper()}/bars"

            params = {
                "timeframe": timeframe,
                "start": start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "limit": 10000,
                "feed": self.feed,
                "adjustment": "raw",
                "end": end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            }

            records = []
            next_page_token = None

            while True:

                if next_page_token:
                    params["page_token"] = next_page_token

                response = requests.get(
                    url,
                    headers=self.headers,
                    params=params,
                    timeout=10
                )

                response.raise_for_status()

                data = response.json()

                bars = data.get("bars")

                if bars is None:
                    note = (
                        data.get("message")
                        or data.get("error")
                    )

                    print(
                        f"Alpaca returned no bars for {symbol}: "
                        f"{note or data}"
                    )

                    return []

                for bar in bars:

                    records.append({
                        "timestamp": bar["t"],
                        "open": float(bar["o"]),
                        "high": float(bar["h"]),
                        "low": float(bar["l"]),
                        "close": float(bar["c"]),
                        "volume": int(bar["v"])
                    })

                next_page_token = data.get("next_page_token")

                if not next_page_token:
                    break

            if not records:
                print(
                    f"No bars returned for {symbol} "
                    f"({period}, {interval})"
                )

                return []

            bars_per_trading_day = {
                "1Min": 390,
                "5Min": 78,
                "15Min": 26,
                "30Min": 13,
                "1Hour": 7,
                "1Day": 1
            }.get(timeframe, 1)

            max_records = bars_per_trading_day * days_back

            if len(records) > max_records:
                records = records[-max_records:]

            return records

        except Exception as e:
            print(
                f"Error fetching historical data for {symbol}: {e}"
            )

            return []

    # -----------------------------------------------------------------
    # Comparative analysis
    # -----------------------------------------------------------------

    def get_fundamental_analysis(self, symbol: str):
        """Read recent standardized fundamentals from SEC EDGAR companyfacts."""

        symbol = symbol.upper()
        cik = self.sec_cik_map.get(symbol)

        if not cik:
            return {
                "status": "pending",
                "message": f"No SEC CIK mapping configured for {symbol}."
            }

        if not SEC_USER_AGENT or "contact@example.com" in SEC_USER_AGENT:
            return {
                "status": "pending",
                "message": "Configure SEC_USER_AGENT with an application name and contact email."
            }

        if symbol in self.sec_cache and time.time() - self.sec_cache[symbol]["timestamp"] < 86400:
            return self.sec_cache[symbol]["data"]

        try:
            response = requests.get(
                f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
                headers={"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"},
                timeout=15
            )
            response.raise_for_status()
            facts = response.json().get("facts", {}).get("us-gaap", {})

            def latest_fact(names, unit="USD"):
                for name in names:
                    entries = facts.get(name, {}).get("units", {}).get(unit, [])
                    filed = [item for item in entries if item.get("form") in {"10-K", "10-Q"}]
                    if filed:
                        return sorted(filed, key=lambda item: item.get("filed", ""))[-1]
                return None

            revenue = latest_fact(["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"])
            net_income = latest_fact(["NetIncomeLoss"])
            assets = latest_fact(["Assets"])
            liabilities = latest_fact(["Liabilities"])
            debt = latest_fact(["LongTermDebtNoncurrent", "LongTermDebtAndFinanceLeaseObligationsNoncurrent"])

            def value(fact):
                return round(float(fact["val"]), 2) if fact else None

            revenue_value = value(revenue)
            net_income_value = value(net_income)
            result = {
                "status": "available",
                "symbol": symbol,
                "source": "SEC EDGAR",
                "as_of": max((fact.get("filed", "") for fact in [revenue, net_income, assets, liabilities, debt] if fact), default=None),
                "metrics": {
                    "revenue": revenue_value,
                    "net_income": net_income_value,
                    "assets": value(assets),
                    "liabilities": value(liabilities),
                    "long_term_debt": value(debt),
                    "net_margin": round(net_income_value / revenue_value, 4) if revenue_value and net_income_value is not None else None
                }
            }
            self.sec_cache[symbol] = {"data": result, "timestamp": time.time()}
            return result
        except Exception as e:
            print(f"SEC fundamentals error for {symbol}: {e}")
            return {"status": "error", "message": "SEC EDGAR data unavailable right now."}

    def get_sentiment_analysis(self, symbol: str, as_of=None):
        """Summarize current or cutoff-date Alpaca news without presenting it as a prediction."""

        symbol = symbol.upper()
        cutoff = None
        if as_of is not None:
            cutoff = datetime.fromisoformat(
                str(as_of).replace("Z", "+00:00")
            )
            if cutoff.tzinfo is None:
                cutoff = cutoff.replace(tzinfo=timezone.utc)
            cache_key = f"{symbol}:{cutoff.isoformat()}"
        else:
            cache_key = symbol

        cached = self.news_cache.get(cache_key)
        if cached and time.time() - cached["timestamp"] < 900:
            return cached["data"]

        try:
            params = {"symbols": symbol, "limit": 50, "sort": "desc"}
            if cutoff is not None:
                window_start = cutoff - timedelta(days=30)
                params["start"] = window_start.isoformat()
                params["end"] = cutoff.isoformat()

            response = requests.get(
                "https://data.alpaca.markets/v1beta1/news",
                headers=self.headers,
                params=params,
                timeout=15
            )
            response.raise_for_status()
            articles = response.json().get("news", [])
            if cutoff is not None:
                eligible_articles = []
                for article in articles:
                    created_at = datetime.fromisoformat(
                        article["created_at"].replace("Z", "+00:00")
                    )
                    updated_at = datetime.fromisoformat(
                        article.get("updated_at", article["created_at"]).replace("Z", "+00:00")
                    )
                    if created_at <= cutoff and updated_at <= cutoff:
                        eligible_articles.append(article)
                articles = eligible_articles

            if not articles:
                if cutoff is not None:
                    return {
                        "status": "pending",
                        "symbol": symbol,
                        "source": "Alpaca News",
                        "as_of": cutoff.isoformat(),
                        "window_start": (cutoff - timedelta(days=30)).isoformat(),
                        "window_end": cutoff.isoformat(),
                        "article_count": 0,
                        "articles": [],
                        "message": "No eligible news was returned in the 30 days through this cutoff."
                    }
                return {"status": "pending", "message": "No recent news returned by Alpaca."}

            positive_words = {"beat", "growth", "profit", "raises", "upgrade", "strong", "record", "outperform"}
            negative_words = {"loss", "cut", "downgrade", "weak", "lawsuit", "risk", "decline", "miss"}
            scored_articles = []
            total_score = 0
            for article in articles:
                text = f"{article.get('headline', '')} {article.get('summary', '')}".lower()
                score = sum(word in text for word in positive_words) - sum(word in text for word in negative_words)
                total_score += score
                scored_articles.append({
                    "headline": article.get("headline", "Untitled"),
                    "source": article.get("source", "Alpaca News"),
                    "created_at": article.get("created_at"),
                    "score": score
                })

            average_score = total_score / len(scored_articles)
            state = "positive" if average_score > 0.25 else "negative" if average_score < -0.25 else "mixed"
            result = {
                "status": "available",
                "symbol": symbol,
                "source": "Alpaca News",
                "as_of": scored_articles[0].get("created_at"),
                "state": state,
                "article_count": len(scored_articles),
                "articles": scored_articles[:5]
            }
            if cutoff is not None:
                result["window_start"] = (cutoff - timedelta(days=30)).isoformat()
                result["window_end"] = cutoff.isoformat()
                result["as_of"] = max(article["created_at"] for article in scored_articles)
            self.news_cache[cache_key] = {"data": result, "timestamp": time.time()}
            return result
        except Exception as e:
            print(f"Alpaca news error for {symbol}: {e}")
            return {"status": "error", "message": "Alpaca News unavailable right now."}

    def get_macro_analysis(self):
        """Read macro context from FRED's public series endpoint."""

        if not FRED_API_KEY:
            return {
                "status": "needs_setup",
                "message": "Configure FRED_API_KEY in backend/.env."
            }

        if self.macro_cache and time.time() - self.macro_cache["timestamp"] < 21600:
            return self.macro_cache["data"]

        series = {
            "FEDFUNDS": "Federal funds rate",
            "CPIAUCSL": "Consumer price index",
            "UNRATE": "Unemployment rate",
            "GDPC1": "Real GDP"
        }

        try:
            metrics = {}
            for series_id, label in series.items():
                response = requests.get(
                    "https://api.stlouisfed.org/fred/series/observations",
                    params={
                        "series_id": series_id,
                        "api_key": FRED_API_KEY,
                        "file_type": "json",
                        "sort_order": "desc",
                        "limit": 2
                    },
                    timeout=15
                )
                response.raise_for_status()
                observations = [
                    item for item in response.json().get("observations", [])
                    if item.get("value") not in {None, "."}
                ]
                if observations:
                    latest = observations[0]
                    previous = observations[1] if len(observations) > 1 else None
                    metrics[series_id] = {
                        "label": label,
                        "value": float(latest["value"]),
                        "previous_value": float(previous["value"]) if previous else None,
                        "date": latest.get("date")
                    }

            result = {"status": "available", "source": "FRED", "metrics": metrics}
            self.macro_cache = {"data": result, "timestamp": time.time()}
            return result
        except Exception as e:
            print(f"FRED macro error: {e}")
            return {"status": "error", "message": "FRED macro data unavailable right now."}

    def get_market_analysis(
        self,
        symbol: str,
        benchmark: str = "SPY",
        sector: str = "XLK",
        period: str = "3mo"
    ):
        """Calculate descriptive volatility, momentum, and correlation metrics."""

        import pandas as pd

        symbol = symbol.upper()
        benchmark = benchmark.upper()
        sector = sector.upper()

        price_records = self.get_historical_data(symbol, period, "1d")
        benchmark_records = self.get_historical_data(benchmark, period, "1d")
        sector_records = self.get_historical_data(sector, period, "1d")

        if len(price_records) < 20 or len(benchmark_records) < 20:
            return {
                "status": "pending",
                "message": "Not enough daily data for comparative analysis."
            }

        def close_series(records):
            frame = pd.DataFrame(records)
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
            return frame.set_index("timestamp")["close"].astype(float).sort_index()

        prices = close_series(price_records)
        benchmark_prices = close_series(benchmark_records)
        sector_prices = close_series(sector_records)
        returns = prices.pct_change().dropna()
        benchmark_returns = benchmark_prices.pct_change().dropna()
        sector_returns = sector_prices.pct_change().dropna()

        aligned = pd.concat(
            [returns.rename("asset"), benchmark_returns.rename("benchmark"), sector_returns.rename("sector")],
            axis=1,
            join="inner"
        ).dropna()

        if len(aligned) < 20:
            return {
                "status": "pending",
                "message": "Not enough overlapping benchmark data."
            }

        lookback = min(20, len(prices) - 1)
        asset_return = prices.iloc[-1] / prices.iloc[-lookback - 1] - 1
        benchmark_return = benchmark_prices.iloc[-1] / benchmark_prices.iloc[-lookback - 1] - 1
        sector_return = sector_prices.iloc[-1] / sector_prices.iloc[-lookback - 1] - 1
        relative_return = asset_return - benchmark_return
        volatility = returns.tail(20).std() * (252 ** 0.5)
        true_range = pd.concat(
            [
                pd.DataFrame(price_records)["high"].astype(float) - pd.DataFrame(price_records)["low"].astype(float),
                (pd.DataFrame(price_records)["high"].astype(float) - pd.DataFrame(price_records)["close"].astype(float).shift()).abs(),
                (pd.DataFrame(price_records)["low"].astype(float) - pd.DataFrame(price_records)["close"].astype(float).shift()).abs()
            ],
            axis=1
        ).max(axis=1)
        atr_percent = (true_range.tail(14).mean() / prices.iloc[-1]) if prices.iloc[-1] else 0
        drawdown = (prices / prices.cummax() - 1).min()

        momentum_state = "positive" if relative_return > 0.02 else "negative" if relative_return < -0.02 else "mixed"
        volatility_state = "elevated" if volatility > 0.35 or atr_percent > 0.03 else "contained" if volatility < 0.15 else "normal"

        def number(value):
            return round(float(value), 4) if pd.notna(value) else None

        return {
            "status": "available",
            "symbol": symbol,
            "period": period,
            "source": "alpaca",
            "as_of": prices.index[-1].isoformat(),
            "fundamental": self.get_fundamental_analysis(symbol),
            "sentiment": self.get_sentiment_analysis(symbol),
            "macro": self.get_macro_analysis(),
            "momentum": {
                "state": momentum_state,
                "asset_return": number(asset_return),
                "benchmark_return": number(benchmark_return),
                "relative_return": number(relative_return),
                "benchmark": benchmark,
                "sector": sector,
                "sector_return": number(sector_return)
            },
            "volatility": {
                "state": volatility_state,
                "realized_20d": number(volatility),
                "atr_14_percent": number(atr_percent),
                "max_drawdown": number(drawdown)
            },
            "correlation": {
                "benchmark": benchmark,
                "benchmark_value": number(aligned["asset"].corr(aligned["benchmark"])),
                "sector": sector,
                "sector_value": number(aligned["asset"].corr(aligned["sector"]))
            }
        }

    # -----------------------------------------------------------------
    # Multiple symbols
    # -----------------------------------------------------------------

    def get_multiple_prices(self, symbols: list):
        """
        Get prices for multiple stocks using Alpaca's
        batched snapshots endpoint.
        """

        current_time = time.time()

        symbol_list = [
            s.strip().upper()
            for s in symbols
        ]

        results = {}
        symbols_to_fetch = []

        for sym in symbol_list:

            cached = self.cache.get(sym)

            if (
                cached
                and current_time - cached["timestamp"]
                < self.cache_timeout
            ):
                results[sym] = cached["data"]

            else:
                symbols_to_fetch.append(sym)

        if symbols_to_fetch:

            try:
                url = f"{self.base_url}/stocks/snapshots"

                params = {
                    "symbols": ",".join(symbols_to_fetch),
                    "feed": self.feed
                }

                response = requests.get(
                    url,
                    headers=self.headers,
                    params=params,
                    timeout=10
                )

                response.raise_for_status()

                data = response.json()

                for sym in symbols_to_fetch:

                    snapshot = data.get(sym)

                    if not snapshot:
                        results[sym] = self._get_mock_price(sym)
                        continue

                    latest_trade = (
                        snapshot.get("latestTrade") or {}
                    )

                    daily_bar = (
                        snapshot.get("dailyBar") or {}
                    )

                    prev_bar = (
                        snapshot.get("prevDailyBar") or {}
                    )

                    current_price = (
                        latest_trade.get("p")
                        or daily_bar.get("c")
                    )

                    previous_close = prev_bar.get("c", 0)

                    if not current_price:
                        results[sym] = self._get_mock_price(sym)
                        continue

                    change = (
                        current_price - previous_close
                        if previous_close
                        else 0
                    )

                    change_percent = (
                        change / previous_close * 100
                        if previous_close
                        else 0
                    )

                    price_data = {
                        "symbol": sym,
                        "current_price": float(current_price),
                        "previous_close": float(previous_close),
                        "open": float(daily_bar.get("o", 0)),
                        "high": float(daily_bar.get("h", 0)),
                        "low": float(daily_bar.get("l", 0)),
                        "volume": int(daily_bar.get("v", 0)),
                        "change": round(change, 2),
                        "change_percent": f"{change_percent:.2f}%",
                        "timestamp": current_time
                    }

                    self.cache[sym] = {
                        "data": price_data,
                        "timestamp": current_time
                    }

                    results[sym] = price_data

            except Exception as e:

                print(
                    f"Error fetching multiple prices "
                    f"from Alpaca: {e}"
                )

                for sym in symbols_to_fetch:
                    results[sym] = self._get_mock_price(sym)

        return results

    # -----------------------------------------------------------------
    # Mock price fallback
    # -----------------------------------------------------------------

    def _get_mock_price(self, symbol: str):
        """
        Fallback mock data if Alpaca is unavailable.
        """

        import random

        base_prices = {
            "AAPL": 178.50,
            "GOOGL": 141.80,
            "MSFT": 378.90,
            "AMZN": 178.25,
            "TSLA": 248.50
        }

        base = base_prices.get(
            symbol.upper(),
            100
        )

        variance = base * 0.02

        return {
            "symbol": symbol.upper(),
            "current_price": round(
                base + random.uniform(-variance, variance),
                2
            ),
            "previous_close": base,
            "open": round(
                base + random.uniform(-variance, variance),
                2
            ),
            "high": round(
                base + random.uniform(0, variance),
                2
            ),
            "low": round(
                base - random.uniform(0, variance),
                2
            ),
            "volume": random.randint(
                1000000,
                10000000
            ),
            "change": round(
                random.uniform(-5, 5),
                2
            ),
            "change_percent": f"{random.uniform(-3, 3):.2f}%",
            "timestamp": time.time()
        }

    # -----------------------------------------------------------------
    # Mock historical fallback
    # -----------------------------------------------------------------

    def _get_mock_historical(
        self,
        symbol: str,
        period: str,
        interval: str = "1d"
    ):
        """
        Fallback mock historical data.
        """

        import random

        base_prices = {
            "AAPL": 178.50,
            "GOOGL": 141.80,
            "MSFT": 378.90,
            "AMZN": 178.25,
            "TSLA": 248.50
        }

        base = base_prices.get(
            symbol.upper(),
            100
        )

        intraday_minutes = {
            "1m": 1,
            "5m": 5,
            "15m": 15,
            "30m": 30,
            "1h": 60
        }

        if interval in intraday_minutes:

            step_minutes = intraday_minutes[interval]

            bars_per_day = max(
                1,
                (6 * 60 + 30) // step_minutes
            )

            period_days = {
                "1d": 1,
                "5d": 5,
                "1mo": 22,
                "3mo": 65,
                "6mo": 130,
                "1y": 260
            }.get(period, 1)

            num_bars = min(
                bars_per_day * period_days,
                2000
            )

            records = []

            now = datetime.now()

            for i in range(num_bars):

                minutes_ago = i * step_minutes

                ts = (
                    now.replace(
                        second=0,
                        microsecond=0
                    )
                    - timedelta(minutes=minutes_ago)
                )

                variance = base * 0.005

                open_price = (
                    base
                    + random.uniform(
                        -variance,
                        variance
                    )
                )

                close_price = (
                    base
                    + random.uniform(
                        -variance,
                        variance
                    )
                )

                high_price = max(
                    open_price,
                    close_price
                ) + random.uniform(
                    0,
                    variance
                )

                low_price = min(
                    open_price,
                    close_price
                ) - random.uniform(
                    0,
                    variance
                )

                records.append({
                    "timestamp": ts.strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                    "open": round(
                        open_price,
                        2
                    ),
                    "high": round(
                        high_price,
                        2
                    ),
                    "low": round(
                        low_price,
                        2
                    ),
                    "close": round(
                        close_price,
                        2
                    ),
                    "volume": random.randint(
                        10000,
                        200000
                    )
                })

                base += random.uniform(
                    -0.3,
                    0.3
                )

            records.reverse()

            return records

        days_map = {
            "1d": 1,
            "5d": 5,
            "1mo": 30,
            "3mo": 90,
            "6mo": 180,
            "1y": 365
        }

        num_days = days_map.get(
            period,
            5
        )

        records = []

        now = datetime.now()

        for i in range(num_days):

            date = now - timedelta(days=i)

            date_str = date.strftime(
                "%Y-%m-%d"
            )

            variance = base * 0.02

            open_price = (
                base
                + random.uniform(
                    -variance,
                    variance
                )
            )

            close_price = (
                base
                + random.uniform(
                    -variance,
                    variance
                )
            )

            high_price = max(
                open_price,
                close_price
            ) + random.uniform(
                0,
                variance
            )

            low_price = min(
                open_price,
                close_price
            ) - random.uniform(
                0,
                variance
            )

            records.append({
                "timestamp": date_str,
                "open": round(
                    open_price,
                    2
                ),
                "high": round(
                    high_price,
                    2
                ),
                "low": round(
                    low_price,
                    2
                ),
                "close": round(
                    close_price,
                    2
                ),
                "volume": random.randint(
                    1000000,
                    10000000
                )
            })

            base += random.uniform(
                -2,
                2
            )

        records.reverse()

        return records

    # -----------------------------------------------------------------
    # Preliminary strategy analysis
    # -----------------------------------------------------------------

    def get_strategy_signals(
        self,
        symbol,
        strategy,
        period="3mo",
        interval="1d",
        end_date=None
    ):
        """
        Generate preliminary strategy analysis.

        IMPORTANT:
        This method does NOT execute trades.

        It returns:
            - chart indicators
            - historical signals
            - current preliminary signal
            - signal strength
            - reasoning
            - risk notes
        """

        import pandas as pd

        records = self.get_historical_data(
            symbol,
            period,
            interval,
            end_date=end_date
        )

        if not records or len(records) < 2:
            return {
                "strategy": strategy,
                "signal": "neutral",
                "strength": "low",
                "current_price": None,
                "reasoning": [
                    "Not enough historical data to perform analysis."
                ],
                "risk_notes": [
                    "Wait for sufficient market data."
                ],
                "signals": []
            }

        df = pd.DataFrame(records)

        df["close"] = pd.to_numeric(
            df["close"],
            errors="coerce"
        )

        df = df.dropna(
            subset=["close"]
        ).reset_index(
            drop=True
        )

        closes = df["close"]

        current_price = closes.iloc[-1]

        # =============================================================
        # MOVING AVERAGE CROSSOVER
        # =============================================================

        if strategy == "moving_average_crossover":

            short_window = 10
            long_window = 30

            short_ma = closes.rolling(
                window=short_window
            ).mean()

            long_ma = closes.rolling(
                window=long_window
            ).mean()

            signals = []

            for i in range(1, len(closes)):

                short_current = short_ma.iloc[i]
                long_current = long_ma.iloc[i]

                short_previous = short_ma.iloc[i - 1]
                long_previous = long_ma.iloc[i - 1]

                if (
                    pd.notna(short_current)
                    and pd.notna(long_current)
                    and pd.notna(short_previous)
                    and pd.notna(long_previous)
                ):

                    if (
                        short_current > long_current
                        and short_previous <= long_previous
                    ):
                        signals.append({
                            "index": i,
                            "timestamp": df["timestamp"].iloc[i],
                            "price": self._clean_number(
                                closes.iloc[i],
                                2
                            ),
                            "type": "buy",
                            "reason": (
                                "Short-term moving average "
                                "crossed above the long-term "
                                "moving average."
                            )
                        })

                    elif (
                        short_current < long_current
                        and short_previous >= long_previous
                    ):
                        signals.append({
                            "index": i,
                            "timestamp": df["timestamp"].iloc[i],
                            "price": self._clean_number(
                                closes.iloc[i],
                                2
                            ),
                            "type": "sell",
                            "reason": (
                                "Short-term moving average "
                                "crossed below the long-term "
                                "moving average."
                            )
                        })

            latest_short = short_ma.iloc[-1]
            latest_long = long_ma.iloc[-1]

            if (
                pd.isna(latest_short)
                or pd.isna(latest_long)
            ):
                signal = "neutral"
                strength = "low"

                reasoning = [
                    "There is not enough data to calculate "
                    "both moving averages."
                ]

            elif latest_short > latest_long:

                signal = "buy"

                strength = self._signal_strength(
                    len(signals),
                    signal
                )

                reasoning = [
                    "The short-term moving average is above "
                    "the long-term moving average."
                ]

                if current_price > latest_long:
                    reasoning.append(
                        "Price is currently above the "
                        "long-term moving average."
                    )

                if signals:
                    last_signal = signals[-1]

                    if last_signal["type"] == "buy":
                        reasoning.append(
                            "A recent bullish crossover was detected."
                        )

            elif latest_short < latest_long:

                signal = "sell"

                strength = self._signal_strength(
                    len(signals),
                    signal
                )

                reasoning = [
                    "The short-term moving average is below "
                    "the long-term moving average."
                ]

                if current_price < latest_long:
                    reasoning.append(
                        "Price is currently below the "
                        "long-term moving average."
                    )

                if signals:
                    last_signal = signals[-1]

                    if last_signal["type"] == "sell":
                        reasoning.append(
                            "A recent bearish crossover was detected."
                        )

            else:

                signal = "neutral"
                strength = "low"

                reasoning = [
                    "The short-term and long-term moving averages "
                    "are currently very close."
                ]
            analysis = self._build_base_analysis(
                strategy="Moving Average Crossover",
                signal=signal,
                strength=strength,
                current_price=current_price,
                reasoning=reasoning,
                risk_notes=[
                    "Moving averages are lagging indicators.",
                    "Crossovers can produce false signals "
                    "during sideways markets.",
                    "The signal should be reviewed together "
                    "with the price chart.",
                    "Trend-following logic: price is already moving up, "
                    "so the trend is likely to continue — buy now, ride "
                    "it further up, and sell even higher later.",
                    "It deliberately does not try to catch the bottom; "
                    "it waits for confirmation that a move is underway, "
                    "then joins in.",
                    "Trade-off: you buy after the price has already "
                    "started rising (not the literal lowest point), but "
                    "you gain confidence that a real trend is forming "
                    "rather than just noise."
                ]
            )

            analysis.update({
                "short_ma": self._series_to_list(
                    short_ma,
                    2
                ),
                "long_ma": self._series_to_list(
                    long_ma,
                    2
                ),
                "indicators": {
                    "short_ma": self._clean_number(
                        latest_short,
                        2
                    ),
                    "long_ma": self._clean_number(
                        latest_long,
                        2
                    )
                },
                "signals": signals
            })

            return analysis

        # =============================================================
        # MEAN REVERSION
        # =============================================================

        elif strategy == "mean_reversion":

            window = 20

            mean = closes.rolling(
                window=window
            ).mean()

            std = closes.rolling(
                window=window
            ).std()

            upper = mean + (2 * std)
            lower = mean - (2 * std)

            signals = []

            for i in range(window, len(closes)):

                price = closes.iloc[i]
                upper_value = upper.iloc[i]
                lower_value = lower.iloc[i]

                if (
                    pd.notna(upper_value)
                    and price > upper_value
                ):
                    signals.append({
                        "index": i,
                        "timestamp": df["timestamp"].iloc[i],
                        "price": self._clean_number(
                            price,
                            2
                        ),
                        "type": "sell",
                        "reason": (
                            "Price moved above the "
                            "upper mean-reversion band."
                        )
                    })

                elif (
                    pd.notna(lower_value)
                    and price < lower_value
                ):
                    signals.append({
                        "index": i,
                        "timestamp": df["timestamp"].iloc[i],
                        "price": self._clean_number(
                            price,
                            2
                        ),
                        "type": "buy",
                        "reason": (
                            "Price moved below the "
                            "lower mean-reversion band."
                        )
                    })

            latest_mean = mean.iloc[-1]
            latest_upper = upper.iloc[-1]
            latest_lower = lower.iloc[-1]

            if (
                pd.isna(latest_mean)
                or pd.isna(latest_upper)
                or pd.isna(latest_lower)
            ):
                signal = "neutral"
                strength = "low"

                reasoning = [
                    "Not enough data to calculate "
                    "the mean-reversion bands."
                ]

            elif current_price < latest_lower:

                signal = "buy"

                reasoning = [
                    "Price is currently below the lower "
                    "mean-reversion band.",
                    "This indicates that price is relatively "
                    "far below its recent average."
                ]

                strength = self._signal_strength(
                    len(signals),
                    signal
                )

            elif current_price > latest_upper:

                signal = "sell"

                reasoning = [
                    "Price is currently above the upper "
                    "mean-reversion band.",
                    "This indicates that price is relatively "
                    "far above its recent average."
                ]

                strength = self._signal_strength(
                    len(signals),
                    signal
                )

            else:

                signal = "neutral"
                strength = "low"

                reasoning = [
                    "Price is currently within the "
                    "normal mean-reversion range."
                ]

            analysis = self._build_base_analysis(
                strategy="Mean Reversion",
                signal=signal,
                strength=strength,
                current_price=current_price,
                reasoning=reasoning,
                risk_notes=[
                    "Prices can remain overextended longer "
                    "than expected.",
                    "Mean reversion can perform poorly "
                    "during strong trends.",
                    "The bands do not guarantee that price "
                    "will return to the mean."
                ]
            )

            analysis.update({
                "mean": self._series_to_list(
                    mean,
                    2
                ),
                "upper": self._series_to_list(
                    upper,
                    2
                ),
                "lower": self._series_to_list(
                    lower,
                    2
                ),
                "indicators": {
                    "mean": self._clean_number(
                        latest_mean,
                        2
                    ),
                    "upper": self._clean_number(
                        latest_upper,
                        2
                    ),
                    "lower": self._clean_number(
                        latest_lower,
                        2
                    )
                },
                "signals": signals
            })

            return analysis

        # =============================================================
        # MOMENTUM
        # =============================================================

        elif strategy == "momentum_trading":

            momentum_period = 10

            roc = (
                closes.pct_change(
                    periods=momentum_period
                )
                * 100
            )

            signals = []

            for i in range(1, len(roc)):

                current_roc = roc.iloc[i]
                previous_roc = roc.iloc[i - 1]

                if (
                    pd.notna(current_roc)
                    and pd.notna(previous_roc)
                ):

                    if (
                        current_roc > 5
                        and previous_roc <= 5
                    ):
                        signals.append({
                            "index": i,
                            "timestamp": df["timestamp"].iloc[i],
                            "price": self._clean_number(
                                closes.iloc[i],
                                2
                            ),
                            "type": "buy",
                            "reason": (
                                "Momentum crossed above "
                                "the +5% threshold."
                            )
                        })

                    elif (
                        current_roc < 0
                        and previous_roc >= 0
                    ):
                        signals.append({
                            "index": i,
                            "timestamp": df["timestamp"].iloc[i],
                            "price": self._clean_number(
                                closes.iloc[i],
                                2
                            ),
                            "type": "sell",
                            "reason": (
                                "Momentum crossed below "
                                "the 0% threshold."
                            )
                        })

            latest_roc = roc.iloc[-1]

            if pd.isna(latest_roc):

                signal = "neutral"
                strength = "low"

                reasoning = [
                    "Not enough data to calculate momentum."
                ]

            elif latest_roc > 5:

                signal = "buy"

                reasoning = [
                    "The 10-period rate of change is above +5%.",
                    "Recent price momentum is positive."
                ]

                strength = self._signal_strength(
                    len(signals),
                    signal
                )

            elif latest_roc < 0:

                signal = "sell"

                reasoning = [
                    "The 10-period rate of change is below 0%.",
                    "Recent price momentum is negative."
                ]

                strength = self._signal_strength(
                    len(signals),
                    signal
                )

            else:

                signal = "neutral"
                strength = "low"

                reasoning = [
                    "Momentum is currently between "
                    "the positive and negative thresholds."
                ]

            analysis = self._build_base_analysis(
                strategy="Momentum Trading",
                signal=signal,
                strength=strength,
                current_price=current_price,
                reasoning=reasoning,
                risk_notes=[
                    "Momentum strategies can enter late "
                    "after a large price move.",
                    "Momentum can reverse quickly.",
                    "Review price structure and market conditions "
                    "before making a decision."
                ]
            )

            analysis.update({
                "roc": self._series_to_list(
                    roc,
                    2
                ),
                "indicators": {
                    "roc": self._clean_number(
                        latest_roc,
                        2
                    )
                },
                "signals": signals
            })

            return analysis

        # =============================================================
        # BREAKOUT
        # =============================================================

        elif strategy == "breakout_strategy":

            window = 20

            resistance = closes.rolling(
                window=window
            ).max()

            support = closes.rolling(
                window=window
            ).min()

            signals = []

            for i in range(window, len(closes)):

                current_price_value = closes.iloc[i]

                previous_resistance = resistance.iloc[i - 1]
                previous_support = support.iloc[i - 1]

                if (
                    pd.notna(previous_resistance)
                    and current_price_value > previous_resistance
                ):

                    signals.append({
                        "index": i,
                        "timestamp": df["timestamp"].iloc[i],
                        "price": self._clean_number(
                            current_price_value,
                            2
                        ),
                        "type": "buy",
                        "reason": (
                            "Price broke above the "
                            "20-period resistance level."
                        )
                    })

                elif (
                    pd.notna(previous_support)
                    and current_price_value < previous_support
                ):

                    signals.append({
                        "index": i,
                        "timestamp": df["timestamp"].iloc[i],
                        "price": self._clean_number(
                            current_price_value,
                            2
                        ),
                        "type": "sell",
                        "reason": (
                            "Price broke below the "
                            "20-period support level."
                        )
                    })

            latest_resistance = resistance.iloc[-1]
            latest_support = support.iloc[-1]

            # Use the previous levels when determining whether the
            # current candle actually broke out.
            previous_resistance = (
                resistance.iloc[-2]
                if len(resistance) >= 2
                else latest_resistance
            )

            previous_support = (
                support.iloc[-2]
                if len(support) >= 2
                else latest_support
            )

            if (
                pd.isna(latest_resistance)
                or pd.isna(latest_support)
            ):

                signal = "neutral"
                strength = "low"

                reasoning = [
                    "Not enough data to calculate "
                    "breakout levels."
                ]

            elif current_price > previous_resistance:

                signal = "buy"

                reasoning = [
                    "Price is currently above the "
                    "recent resistance level.",
                    "This indicates a potential upside breakout."
                ]

                strength = self._signal_strength(
                    len(signals),
                    signal
                )

            elif current_price < previous_support:

                signal = "sell"

                reasoning = [
                    "Price is currently below the "
                    "recent support level.",
                    "This indicates a potential downside breakout."
                ]

                strength = self._signal_strength(
                    len(signals),
                    signal
                )

            else:

                signal = "neutral"
                strength = "low"

                reasoning = [
                    "Price is currently trading within "
                    "the recent support/resistance range."
                ]

            analysis = self._build_base_analysis(
                strategy="Breakout Strategy",
                signal=signal,
                strength=strength,
                current_price=current_price,
                reasoning=reasoning,
                risk_notes=[
                    "Breakouts can produce false signals.",
                    "A breakout is stronger when supported "
                    "by volume and sustained price movement.",
                    "Consider waiting for confirmation "
                    "before executing a trade."
                ]
            )

            analysis.update({
                "resistance": self._series_to_list(
                    resistance,
                    2
                ),
                "support": self._series_to_list(
                    support,
                    2
                ),
                "indicators": {
                    "resistance": self._clean_number(
                        latest_resistance,
                        2
                    ),
                    "support": self._clean_number(
                        latest_support,
                        2
                    )
                },
                "signals": signals
            })

            return analysis

        # =============================================================
        # SWING TRADING / RSI
        # =============================================================

        elif strategy == "swing_trading":

            period_rsi = 14

            delta = closes.diff()

            gain = (
                delta.clip(lower=0)
                .rolling(period_rsi)
                .mean()
            )

            loss = (
                -delta.clip(upper=0)
                .rolling(period_rsi)
                .mean()
            )

            # Avoid division errors.
            rs = gain / loss.replace(
                0,
                float("nan")
            )

            rsi = 100 - (
                100 / (1 + rs)
            )

            signals = []

            for i in range(1, len(rsi)):

                current_rsi = rsi.iloc[i]
                previous_rsi = rsi.iloc[i - 1]

                if (
                    pd.notna(current_rsi)
                    and pd.notna(previous_rsi)
                ):

                    if (
                        current_rsi < 30
                        and previous_rsi >= 30
                    ):

                        signals.append({
                            "index": i,
                            "timestamp": df["timestamp"].iloc[i],
                            "price": self._clean_number(
                                closes.iloc[i],
                                2
                            ),
                            "type": "buy",
                            "reason": (
                                "RSI crossed below the "
                                "30 oversold level."
                            )
                        })

                    elif (
                        current_rsi > 70
                        and previous_rsi <= 70
                    ):

                        signals.append({
                            "index": i,
                            "timestamp": df["timestamp"].iloc[i],
                            "price": self._clean_number(
                                closes.iloc[i],
                                2
                            ),
                            "type": "sell",
                            "reason": (
                                "RSI crossed above the "
                                "70 overbought level."
                            )
                        })

            latest_rsi = rsi.iloc[-1]

            if pd.isna(latest_rsi):

                signal = "neutral"
                strength = "low"

                reasoning = [
                    "Not enough data to calculate RSI."
                ]

            elif latest_rsi < 30:

                signal = "buy"

                reasoning = [
                    f"RSI is currently {latest_rsi:.1f}, "
                    "which is below the traditional "
                    "30 oversold threshold."
                ]

                strength = self._signal_strength(
                    len(signals),
                    signal
                )

            elif latest_rsi > 70:

                signal = "sell"

                reasoning = [
                    f"RSI is currently {latest_rsi:.1f}, "
                    "which is above the traditional "
                    "70 overbought threshold."
                ]

                strength = self._signal_strength(
                    len(signals),
                    signal
                )

            else:

                signal = "neutral"
                strength = "low"

                reasoning = [
                    f"RSI is currently {latest_rsi:.1f}, "
                    "which is between the traditional "
                    "oversold and overbought levels."
                ]

            analysis = self._build_base_analysis(
                strategy="Swing Trading",
                signal=signal,
                strength=strength,
                current_price=current_price,
                reasoning=reasoning,
                risk_notes=[
                    "RSI can remain overbought or oversold "
                    "during strong trends.",
                    "An RSI signal by itself does not confirm "
                    "a price reversal.",
                    "Review price action and trend direction "
                    "before executing a trade."
                ]
            )

            analysis.update({
                "rsi": self._series_to_list(
                    rsi,
                    2
                ),
                "indicators": {
                    "rsi": self._clean_number(
                        latest_rsi,
                        2
                    )
                },
                "signals": signals
            })

            return analysis

        # =============================================================
        # UNSUPPORTED STRATEGY
        # =============================================================

        return {
            "strategy": strategy,
            "signal": "neutral",
            "strength": "low",
            "current_price": self._clean_number(
                current_price,
                2
            ),
            "reasoning": [
                f"The strategy '{strategy}' "
                "is not implemented yet."
            ],
            "risk_notes": [
                "No trading decision should be made "
                "from this strategy."
            ],
            "indicators": {},
            "signals": []
        }

    def evaluate_historical_prediction(
        self,
        symbol: str,
        strategy: str,
        cutoff_date: str,
        horizon_days: int = 10,
        period: str = "3mo"
    ):
        """Generate a cutoff-date analysis and compare it with later prices."""

        cutoff = datetime.fromisoformat(cutoff_date).replace(
            hour=23,
            minute=59,
            second=59,
            tzinfo=timezone.utc
        )
        horizon_days = max(1, min(int(horizon_days), 60))
        analysis = self.get_strategy_signals(
            symbol,
            strategy,
            period,
            "1d",
            end_date=cutoff.isoformat()
        )
        analysis["sentiment"] = self.get_sentiment_analysis(
            symbol,
            as_of=cutoff.isoformat()
        )
        cutoff_history = self.get_historical_data(
            symbol,
            period,
            "1d",
            end_date=cutoff.isoformat()
        )

        future_start = cutoff + timedelta(days=1)
        future_end = cutoff + timedelta(days=horizon_days + 10)
        future_records = self.get_historical_data(
            symbol,
            "1y",
            "1d",
            start_date=future_start.isoformat(),
            end_date=future_end.isoformat()
        )
        entry_price = float(analysis.get("current_price") or 0)
        cutoff_record = cutoff_history[-1] if cutoff_history else None
        evaluation_history = []
        if cutoff_record:
            evaluation_history.append({
                "timestamp": cutoff_record["timestamp"],
                "close": entry_price,
                "phase": "cutoff"
            })
        evaluation_history.extend(
            {
                "timestamp": record["timestamp"],
                "close": float(record["close"]),
                "phase": "evaluation"
            }
            for record in future_records[:horizon_days]
        )

        if not future_records:
            return {
                "status": "pending",
                "message": "No later market data exists for this cutoff date.",
                "cutoff_date": cutoff_date,
                "analysis": analysis,
                "price_history": cutoff_history,
                "evaluation_history": evaluation_history,
                "horizon_days": horizon_days
            }

        if len(future_records) < horizon_days:
            return {
                "status": "pending",
                "message": (
                    f"Only {len(future_records)} trading sessions are "
                    f"available after this cutoff; {horizon_days} are needed."
                ),
                "cutoff_date": cutoff_date,
                "analysis": analysis,
                "price_history": cutoff_history,
                "evaluation_history": evaluation_history,
                "horizon_days": horizon_days
            }

        horizon_record = future_records[horizon_days - 1]
        exit_price = float(horizon_record["close"])
        future_return = (exit_price / entry_price - 1) if entry_price else None
        signal = analysis.get("signal", "neutral")
        direction = 1 if signal == "buy" else -1 if signal == "sell" else 0
        correct = None if direction == 0 or future_return is None else direction * future_return > 0

        return {
            "status": "available",
            "symbol": symbol.upper(),
            "strategy": strategy,
            "cutoff_date": cutoff_date,
            "horizon_days": horizon_days,
            "analysis": analysis,
            "price_history": cutoff_history,
            "evaluation_history": evaluation_history,
            "outcome": {
                "entry_price": round(entry_price, 2),
                "exit_date": horizon_record["timestamp"],
                "exit_price": round(exit_price, 2),
                "future_return": round(future_return, 4) if future_return is not None else None,
                "signal": signal,
                "correct": correct
            },
            "warning": "Historical comparison is descriptive and does not prove future performance."
        }


# ---------------------------------------------------------------------
# Global service instance
# ---------------------------------------------------------------------

stock_service = StockService()