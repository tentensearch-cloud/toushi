"""
株価データ取得モジュール
yfinanceを使用して日本株の株価データを取得する
パフォーマンス向上のため、yf.downloadによる一括取得を行う
"""
import time
import logging
import yfinance as yf
import pandas as pd
from config import DATA_PARAMS, WATCHLIST

logger = logging.getLogger(__name__)

def fetch_stock_data_batch(tickers: list, period: str = None, interval: str = None) -> dict[str, pd.DataFrame]:
    """
    複数銘柄のデータを一括取得する
    """
    if period is None:
        period = DATA_PARAMS["daily_period"]
    if interval is None:
        interval = DATA_PARAMS["daily_interval"]

    if not tickers:
        return {}

    # ティッカーリストをスペース区切り文字列に変換
    tickers_str = " ".join(tickers)
    
    logger.info(f"一括データ取得開始: {len(tickers)}銘柄 ({period}, {interval})")
    
    try:
        # yf.downloadで一括取得 (timeout設定)
        # multi-level columnになるため、後で整形が必要
        data = yf.download(
            tickers_str, 
            period=period, 
            interval=interval, 
            group_by='ticker', 
            auto_adjust=True, 
            prepost=False, 
            threads=True,
            timeout=20  # 20秒タイムアウト
        )
        
        result = {}
        
        # 1銘柄の場合と複数銘柄の場合で構造が違う場合がある
        if len(tickers) == 1:
            ticker = tickers[0]
            if not data.empty:
                result[ticker] = data
            return result

        # 複数銘柄の場合、Top level columnがticker
        for ticker in tickers:
            try:
                # 該当Tickerのデータを抽出
                df = data[ticker].copy()
                # 全行NaNならデータなしとみなす
                if df.isnull().all().all():
                    logger.warning(f"[{ticker}] データが空（NaN）です")
                    continue
                
                # dropnaしてからチェック
                df.dropna(how='all', inplace=True)
                
                if not df.empty:
                    result[ticker] = df
                else:
                    logger.warning(f"[{ticker}] 有効なデータ行がありません")
                    
            except KeyError:
                logger.warning(f"[{ticker}] データが含まれていません")
                continue
                
        logger.info(f"一括取得完了: {len(result)}/{len(tickers)}銘柄成功")
        return result

    except Exception as e:
        logger.error(f"一括データ取得などでエラー発生: {e}")
        return {}

def fetch_daily_data_batch() -> dict[str, pd.DataFrame]:
    """全監視銘柄の日足データを一括取得"""
    return fetch_stock_data_batch(
        list(WATCHLIST.keys()),
        period=DATA_PARAMS["daily_period"],
        interval=DATA_PARAMS["daily_interval"]
    )

# 古い関数（後方互換性のため残すが、推奨しない）
def fetch_daily_data(ticker: str) -> pd.DataFrame | None:
    res = fetch_stock_data_batch([ticker])
    return res.get(ticker)
