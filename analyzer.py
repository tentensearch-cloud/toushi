"""
テクニカル分析エンジン
移動平均、RSI、MACD、ボリンジャーバンド、出来高分析を計算する
"""
import logging
import numpy as np
import pandas as pd
from config import ANALYSIS_PARAMS

logger = logging.getLogger(__name__)


def calculate_sma(series: pd.Series, period: int) -> pd.Series:
    """単純移動平均線"""
    return series.rolling(window=period, min_periods=1).mean()


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """指数移動平均線"""
    return series.ewm(span=period, adjust=False).mean()


def calculate_rsi(series: pd.Series, period: int = None) -> pd.Series:
    """RSI (Relative Strength Index)"""
    if period is None:
        period = ANALYSIS_PARAMS["rsi_period"]

    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_macd(series: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    MACD (Moving Average Convergence Divergence)

    Returns:
        (macd_line, signal_line, histogram)
    """
    fast = ANALYSIS_PARAMS["macd_fast"]
    slow = ANALYSIS_PARAMS["macd_slow"]
    signal = ANALYSIS_PARAMS["macd_signal"]

    ema_fast = calculate_ema(series, fast)
    ema_slow = calculate_ema(series, slow)

    macd_line = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, signal)
    histogram = macd_line - signal_line

    return macd_line, signal_line, histogram


def calculate_bollinger_bands(series: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    ボリンジャーバンド

    Returns:
        (upper_band, middle_band, lower_band)
    """
    period = ANALYSIS_PARAMS["bb_period"]
    std_dev = ANALYSIS_PARAMS["bb_std"]

    middle = calculate_sma(series, period)
    rolling_std = series.rolling(window=period, min_periods=1).std()

    upper = middle + (rolling_std * std_dev)
    lower = middle - (rolling_std * std_dev)

    return upper, middle, lower


def analyze_stock(df: pd.DataFrame) -> dict:
    """
    1銘柄の包括的テクニカル分析を行う

    Args:
        df: 株価データ（Open, High, Low, Close, Volume列を含む）

    Returns:
        分析結果の辞書
    """
    if df is None or df.empty or len(df) < 5:
        return {"error": "データ不足"}

    close = df["Close"]
    volume = df["Volume"]
    current_price = float(close.iloc[-1])

    result = {
        "current_price": current_price,
        "signals": {},
        "indicators": {},
        "score": 0.0,
    }

    # --- 移動平均線分析 ---
    sma_short = calculate_sma(close, ANALYSIS_PARAMS["sma_short"])
    sma_medium = calculate_sma(close, ANALYSIS_PARAMS["sma_medium"])
    sma_long = calculate_sma(close, ANALYSIS_PARAMS["sma_long"])

    result["indicators"]["sma_short"] = float(sma_short.iloc[-1])
    result["indicators"]["sma_medium"] = float(sma_medium.iloc[-1])
    result["indicators"]["sma_long"] = float(sma_long.iloc[-1]) if len(df) >= ANALYSIS_PARAMS["sma_long"] else None

    # ゴールデンクロス / デッドクロス判定
    ma_signal = 0
    if len(sma_short) >= 2 and len(sma_medium) >= 2:
        prev_short = float(sma_short.iloc[-2])
        prev_medium = float(sma_medium.iloc[-2])
        curr_short = float(sma_short.iloc[-1])
        curr_medium = float(sma_medium.iloc[-1])

        if prev_short <= prev_medium and curr_short > curr_medium:
            ma_signal = 1  # ゴールデンクロス（買い）
        elif prev_short >= prev_medium and curr_short < curr_medium:
            ma_signal = -1  # デッドクロス（売り）
        elif curr_short > curr_medium:
            ma_signal = 0.5  # 短期が中期の上（やや強気）
        else:
            ma_signal = -0.5  # 短期が中期の下（やや弱気）

    result["signals"]["ma_cross"] = ma_signal

    # --- RSI分析 ---
    rsi = calculate_rsi(close)
    current_rsi = float(rsi.iloc[-1])
    result["indicators"]["rsi"] = current_rsi

    rsi_signal = 0
    if current_rsi <= ANALYSIS_PARAMS["rsi_oversold"]:
        rsi_signal = 1  # 売られすぎ = 買いシグナル
    elif current_rsi >= ANALYSIS_PARAMS["rsi_overbought"]:
        rsi_signal = -1  # 買われすぎ = 売りシグナル
    elif current_rsi <= 40:
        rsi_signal = 0.5
    elif current_rsi >= 60:
        rsi_signal = -0.5

    result["signals"]["rsi"] = rsi_signal

    # --- MACD分析 ---
    macd_line, signal_line, histogram = calculate_macd(close)

    result["indicators"]["macd"] = float(macd_line.iloc[-1])
    result["indicators"]["macd_signal"] = float(signal_line.iloc[-1])
    result["indicators"]["macd_histogram"] = float(histogram.iloc[-1])

    macd_signal = 0
    if len(histogram) >= 2:
        prev_hist = float(histogram.iloc[-2])
        curr_hist = float(histogram.iloc[-1])

        if prev_hist <= 0 and curr_hist > 0:
            macd_signal = 1  # MACDがシグナルを上抜け（買い）
        elif prev_hist >= 0 and curr_hist < 0:
            macd_signal = -1  # MACDがシグナルを下抜け（売り）
        elif curr_hist > 0 and curr_hist > prev_hist:
            macd_signal = 0.5  # ヒストグラム拡大（強気）
        elif curr_hist < 0 and curr_hist < prev_hist:
            macd_signal = -0.5  # ヒストグラム拡大（弱気）

    result["signals"]["macd"] = macd_signal

    # --- ボリンジャーバンド分析 ---
    bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(close)

    result["indicators"]["bb_upper"] = float(bb_upper.iloc[-1])
    result["indicators"]["bb_middle"] = float(bb_middle.iloc[-1])
    result["indicators"]["bb_lower"] = float(bb_lower.iloc[-1])

    bb_signal = 0
    bb_width = (float(bb_upper.iloc[-1]) - float(bb_lower.iloc[-1])) / float(bb_middle.iloc[-1])
    result["indicators"]["bb_width"] = bb_width

    if current_price <= float(bb_lower.iloc[-1]):
        bb_signal = 1  # 下限バンドタッチ（買い）
    elif current_price >= float(bb_upper.iloc[-1]):
        bb_signal = -1  # 上限バンドタッチ（売り）
    elif current_price < float(bb_middle.iloc[-1]):
        bb_signal = 0.3
    else:
        bb_signal = -0.3

    result["signals"]["bb"] = bb_signal

    # --- 出来高分析 ---
    vol_avg = volume.rolling(window=ANALYSIS_PARAMS["volume_avg_period"], min_periods=1).mean()
    current_vol = float(volume.iloc[-1])
    avg_vol = float(vol_avg.iloc[-1])

    result["indicators"]["volume"] = current_vol
    result["indicators"]["volume_avg"] = avg_vol
    vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0
    result["indicators"]["volume_ratio"] = vol_ratio

    # 出来高急増 + 価格方向でシグナル判定
    vol_signal = 0
    if vol_ratio >= ANALYSIS_PARAMS["volume_spike_multiplier"]:
        price_change = (current_price - float(close.iloc[-2])) / float(close.iloc[-2]) * 100 if len(close) >= 2 else 0
        if price_change > 0:
            vol_signal = 0.8  # 出来高増 + 上昇 → 強い買い
        else:
            vol_signal = -0.8  # 出来高増 + 下落 → 強い売り

    result["signals"]["volume"] = vol_signal

    # --- 価格モメンタム ---
    if len(close) >= 2:
        price_change_pct = (current_price - float(close.iloc[-2])) / float(close.iloc[-2]) * 100
        result["indicators"]["price_change_pct"] = price_change_pct

        momentum_signal = 0
        if price_change_pct >= ANALYSIS_PARAMS["price_change_threshold"]:
            momentum_signal = 0.7  # 急騰
        elif price_change_pct <= -ANALYSIS_PARAMS["price_change_threshold"]:
            momentum_signal = -0.7  # 急落
        else:
            momentum_signal = price_change_pct / ANALYSIS_PARAMS["price_change_threshold"] * 0.5

        result["signals"]["price_momentum"] = momentum_signal
    else:
        result["signals"]["price_momentum"] = 0

    # --- 総合スコア計算 ---
    from config import SIGNAL_PARAMS

    score = (
        result["signals"].get("ma_cross", 0) * SIGNAL_PARAMS["weight_ma_cross"]
        + result["signals"].get("rsi", 0) * SIGNAL_PARAMS["weight_rsi"]
        + result["signals"].get("macd", 0) * SIGNAL_PARAMS["weight_macd"]
        + result["signals"].get("bb", 0) * SIGNAL_PARAMS["weight_bb"]
        + result["signals"].get("volume", 0) * SIGNAL_PARAMS["weight_volume"]
        + result["signals"].get("price_momentum", 0) * SIGNAL_PARAMS["weight_price_momentum"]
    )
    result["score"] = round(score, 4)

    # --- シグナル判定 ---
    if score >= SIGNAL_PARAMS["buy_threshold"]:
        result["action"] = "BUY"
    elif score <= SIGNAL_PARAMS["sell_threshold"]:
        result["action"] = "SELL"
    else:
        result["action"] = "HOLD"

    return result
