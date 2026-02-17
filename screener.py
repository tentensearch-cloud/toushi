"""
スクリーニング＆シグナル生成モジュール
全銘柄を分析し、買い候補TOP10を生成する
"""
import json
import os
import logging
from datetime import datetime, timedelta
from config import WATCHLIST, SIGNAL_PARAMS, RISK_PARAMS, SIGNAL_HISTORY_FILE
from data_fetcher import fetch_daily_data_batch
from analyzer import analyze_stock
from portfolio import get_available_cash, get_holdings, calculate_recommended_shares

logger = logging.getLogger(__name__)


def _load_signal_history() -> dict:
    """シグナル履歴を読み込む（重複通知防止用）"""
    if os.path.exists(SIGNAL_HISTORY_FILE):
        try:
            with open(SIGNAL_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _save_signal_history(history: dict):
    """シグナル履歴を保存"""
    try:
        with open(SIGNAL_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except IOError as e:
        logger.error(f"シグナル履歴の保存に失敗: {e}")


def _is_duplicate_signal(ticker: str, action: str, history: dict) -> bool:
    """同一シグナルの重複チェック（6時間以内の同一シグナルは重複として扱う）"""
    key = f"{ticker}_{action}"
    if key in history:
        last_time = datetime.fromisoformat(history[key])
        if datetime.now() - last_time < timedelta(hours=6):
            return True
    return False


def _record_signal(ticker: str, action: str, history: dict):
    """シグナルを履歴に記録"""
    key = f"{ticker}_{action}"
    history[key] = datetime.now().isoformat()


def calculate_oco_levels(current_price: float) -> dict:
    """OCO注文の利確・損切りラインを計算"""
    take_profit = current_price * (1 + RISK_PARAMS["take_profit_pct"] / 100)
    stop_loss = current_price * (1 - RISK_PARAMS["stop_loss_pct"] / 100)
    return {
        "take_profit": round(take_profit, 1),
        "stop_loss": round(stop_loss, 1),
        "take_profit_pct": RISK_PARAMS["take_profit_pct"],
        "stop_loss_pct": RISK_PARAMS["stop_loss_pct"],
    }


def determine_buy_method(price: float, available_cash: float) -> dict:
    """
    100株（単元株）かS株（1株単位）かを判定する

    Returns:
        {"method": "単元株(100株)" or "S株(1株〜)",
         "shares": 推奨株数,
         "estimated_cost": 推定コスト}
    """
    if price <= 0:
        return {"method": "購入不可", "shares": 0, "estimated_cost": 0}

    unit_cost = price * 100  # 単元株（100株）のコスト

    if unit_cost <= available_cash:
        # 100株単位で購入可能
        max_units = int(available_cash / unit_cost)
        shares = max_units * 100
        # 1銘柄あたりの上限チェック
        max_investment = available_cash * (RISK_PARAMS["max_per_stock_pct"] / 100)
        if shares * price > max_investment:
            shares = (int(max_investment / unit_cost)) * 100
            shares = max(shares, 100)
        return {
            "method": "単元株(100株)",
            "shares": shares,
            "estimated_cost": round(price * shares, 0),
        }
    else:
        # S株（1株単位）で購入
        max_shares = int(available_cash / price)
        max_investment = available_cash * (RISK_PARAMS["max_per_stock_pct"] / 100)
        if max_shares * price > max_investment:
            max_shares = int(max_investment / price)
        max_shares = max(max_shares, 1) if price <= available_cash else 0
        return {
            "method": "S株(1株〜)",
            "shares": max_shares,
            "estimated_cost": round(price * max_shares, 0),
        }


def screen_all_stocks() -> dict:
    """
    全監視銘柄をスクリーニングし、買い候補TOP10を生成する

    Returns:
        {
            "top_candidates": [...],     # 買い候補TOP10（常に10社）
            "holdings_alerts": [...],    # 保有銘柄アラート
            "summary": {...},
            "all_results": {...},
        }
    """
    signal_history = _load_signal_history()
    holdings = get_holdings()
    available_cash = get_available_cash()

    all_candidates = []  # スコア上位の買い候補
    holdings_alerts = []
    all_results = {}

    logger.info(f"スクリーニング開始: {len(WATCHLIST)}銘柄, 利用可能残高: ¥{available_cash:,.0f}")

    # 一括データ取得（高速化・API制限対策）
    all_stock_data = fetch_daily_data_batch()

    for ticker, name in WATCHLIST.items():
        try:
            df = all_stock_data.get(ticker)
            if df is None or df.empty:
                # logger.warning(f"[{ticker}] {name}: データ取得失敗、スキップ") # ログ多すぎるので省略
                continue

            result = analyze_stock(df)
            if "error" in result:
                logger.warning(f"[{ticker}] {name}: 分析エラー: {result['error']}")
                continue

            result["ticker"] = ticker
            result["name"] = name
            all_results[ticker] = result

            current_price = result.get("current_price", 0)
            score = result.get("score", 0)

            # === 保有銘柄のアラート（利確・損切りのみ） ===
            if ticker in holdings:
                holding = holdings[ticker]
                pnl_pct = (current_price / holding["avg_price"] - 1) * 100

                if pnl_pct >= RISK_PARAMS["take_profit_pct"]:
                    holdings_alerts.append({
                        **result,
                        "alert_type": "TAKE_PROFIT",
                        "pnl_pct": round(pnl_pct, 2),
                        "holding": holding,
                    })
                elif pnl_pct <= -RISK_PARAMS["stop_loss_pct"]:
                    holdings_alerts.append({
                        **result,
                        "alert_type": "STOP_LOSS",
                        "pnl_pct": round(pnl_pct, 2),
                        "holding": holding,
                    })
            else:
                # 未保有の銘柄のみ買い候補として評価
                # スコアがプラスの銘柄のみ（危険な株=マイナススコアは除外）
                if score > 0:
                    buy_info = determine_buy_method(current_price, available_cash)
                    oco = calculate_oco_levels(current_price)
                    all_candidates.append({
                        **result,
                        **buy_info,
                        "oco": oco,
                    })

        except Exception as e:
            logger.error(f"[{ticker}] {name}: スクリーニングエラー: {e}")
            continue

    # スコア上位10社を買い候補として選出
    all_candidates.sort(key=lambda x: x["score"], reverse=True)
    top_candidates = all_candidates[:10]

    # シグナル履歴を保存
    _save_signal_history(signal_history)

    summary = {
        "total_screened": len(WATCHLIST),
        "data_available": len(all_results),
        "top_candidates": len(top_candidates),
        "holdings_alerts": len(holdings_alerts),
        "available_cash": available_cash,
        "current_positions": len(holdings),
        "timestamp": datetime.now().isoformat(),
    }

    logger.info(
        f"スクリーニング完了: "
        f"買い候補{len(top_candidates)}件, "
        f"保有アラート{len(holdings_alerts)}件"
    )

    return {
        "top_candidates": top_candidates,
        "holdings_alerts": holdings_alerts,
        "summary": summary,
        "all_results": all_results,
    }
