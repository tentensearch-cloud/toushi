"""
株価データ取得モジュール
yfinanceを使用して日本株の株価データを取得する
"""
import time
import logging
import yfinance as yf
import pandas as pd
from config import DATA_PARAMS, WATCHLIST

logger = logging.getLogger(__name__)


def fetch_stock_data(ticker: str, period: str = None, interval: str = None) -> pd.DataFrame | None:
    """
    指定銘柄の株価データを取得する

    Args:
        ticker: ティッカーシンボル（例: "7203.T"）
        period: データ取得期間（例: "1d", "3mo"）
        interval: データ間隔（例: "5m", "1d"）

    Returns:
        株価データのDataFrame、失敗時はNone
    """
    if period is None:
        period = DATA_PARAMS["daily_period"]
    if interval is None:
        interval = DATA_PARAMS["daily_interval"]

    for attempt in range(DATA_PARAMS["retry_count"]):
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period=period, interval=interval)

            if df.empty:
                logger.warning(f"[{ticker}] データが空です (period={period}, interval={interval})")
                return None

            logger.info(f"[{ticker}] {len(df)}行のデータを取得 (period={period}, interval={interval})")
            return df

        except Exception as e:
            logger.warning(f"[{ticker}] データ取得失敗 (試行 {attempt + 1}/{DATA_PARAMS['retry_count']}): {e}")
            if attempt < DATA_PARAMS["retry_count"] - 1:
                time.sleep(DATA_PARAMS["retry_delay"])

    logger.error(f"[{ticker}] データ取得に完全に失敗しました")
    return None


def fetch_intraday_data(ticker: str) -> pd.DataFrame | None:
    """イントラデイ（5分足）データを取得"""
    return fetch_stock_data(
        ticker,
        period=DATA_PARAMS["intraday_period"],
        interval=DATA_PARAMS["intraday_interval"]
    )


def fetch_daily_data(ticker: str) -> pd.DataFrame | None:
    """日足データを取得（テクニカル分析用）"""
    return fetch_stock_data(
        ticker,
        period=DATA_PARAMS["daily_period"],
        interval=DATA_PARAMS["daily_interval"]
    )


def fetch_all_watchlist(use_intraday: bool = False) -> dict[str, pd.DataFrame]:
    """
    監視銘柄リスト全体のデータを取得する

    Args:
        use_intraday: Trueの場合イントラデイデータ、Falseの場合日足データ

    Returns:
        {ティッカー: DataFrame} の辞書
    """
    results = {}
    fetch_func = fetch_intraday_data if use_intraday else fetch_daily_data

    for ticker in WATCHLIST:
        df = fetch_func(ticker)
        if df is not None and not df.empty:
            results[ticker] = df
        # レート制限対策
        time.sleep(0.5)

    logger.info(f"全{len(WATCHLIST)}銘柄中{len(results)}銘柄のデータを取得しました")
    return results


def get_current_price(ticker: str) -> float | None:
    """指定銘柄の最新価格を取得"""
    try:
        stock = yf.Ticker(ticker)
        info = stock.fast_info
        return info.get("lastPrice") or info.get("last_price")
    except Exception as e:
        logger.warning(f"[{ticker}] 最新価格の取得に失敗: {e}")
        # フォールバック: 直近のデータから取得
        df = fetch_stock_data(ticker, period="1d", interval="1m")
        if df is not None and not df.empty:
            return float(df["Close"].iloc[-1])
        return None
