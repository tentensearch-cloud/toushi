"""
ポートフォリオ管理モジュール
元手22万円の資金管理、売買履歴の追跡、現在残高の計算を行う
"""
import json
import os
import logging
from datetime import datetime
from config import INITIAL_CAPITAL, PORTFOLIO_FILE, RISK_PARAMS

logger = logging.getLogger(__name__)


def _load_portfolio() -> dict:
    """ポートフォリオデータを読み込む"""
    if os.path.exists(PORTFOLIO_FILE):
        try:
            with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"ポートフォリオファイルの読み込みに失敗: {e}")

    # 初期データ
    return {
        "initial_capital": INITIAL_CAPITAL,
        "current_cash": INITIAL_CAPITAL,
        "trades": [],
        "holdings": {},
        "total_realized_pnl": 0,
        "updated_at": datetime.now().isoformat(),
    }


def _save_portfolio(data: dict):
    """ポートフォリオデータを保存する"""
    data["updated_at"] = datetime.now().isoformat()
    try:
        with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("ポートフォリオデータを保存しました")
    except IOError as e:
        logger.error(f"ポートフォリオデータの保存に失敗: {e}")


def get_portfolio_summary() -> dict:
    """現在のポートフォリオサマリーを取得"""
    portfolio = _load_portfolio()

    # 保有銘柄の時価評価額を計算
    holdings_value = 0
    holdings_detail = []
    for ticker, holding in portfolio.get("holdings", {}).items():
        from data_fetcher import get_current_price
        current_price = get_current_price(ticker)
        if current_price:
            value = current_price * holding["shares"]
            pnl = (current_price - holding["avg_price"]) * holding["shares"]
            pnl_pct = (current_price / holding["avg_price"] - 1) * 100
            holdings_value += value
            holdings_detail.append({
                "ticker": ticker,
                "name": holding.get("name", ticker),
                "shares": holding["shares"],
                "avg_price": holding["avg_price"],
                "current_price": current_price,
                "value": value,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
            })

    total_value = portfolio["current_cash"] + holdings_value
    total_pnl = total_value - portfolio["initial_capital"]
    total_pnl_pct = (total_value / portfolio["initial_capital"] - 1) * 100

    return {
        "initial_capital": portfolio["initial_capital"],
        "current_cash": portfolio["current_cash"],
        "holdings_value": holdings_value,
        "total_value": total_value,
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "total_realized_pnl": portfolio.get("total_realized_pnl", 0),
        "holdings": holdings_detail,
        "trade_count": len(portfolio.get("trades", [])),
    }


def record_buy(ticker: str, name: str, price: float, shares: int) -> dict:
    """
    買い取引を記録する

    Args:
        ticker: ティッカー
        name: 銘柄名
        price: 購入価格
        shares: 購入株数

    Returns:
        更新後のポートフォリオサマリー
    """
    portfolio = _load_portfolio()
    total_cost = price * shares

    if total_cost > portfolio["current_cash"]:
        logger.error(f"資金不足: 必要額 ¥{total_cost:,.0f} > 残高 ¥{portfolio['current_cash']:,.0f}")
        return {"error": "資金不足"}

    # 現金を減らす
    portfolio["current_cash"] -= total_cost

    # 保有銘柄を更新
    if ticker in portfolio["holdings"]:
        existing = portfolio["holdings"][ticker]
        total_shares = existing["shares"] + shares
        avg_price = (existing["avg_price"] * existing["shares"] + price * shares) / total_shares
        portfolio["holdings"][ticker] = {
            "name": name,
            "shares": total_shares,
            "avg_price": round(avg_price, 1),
            "first_buy_date": existing.get("first_buy_date", datetime.now().isoformat()),
        }
    else:
        portfolio["holdings"][ticker] = {
            "name": name,
            "shares": shares,
            "avg_price": price,
            "first_buy_date": datetime.now().isoformat(),
        }

    # 取引履歴に追加
    portfolio["trades"].append({
        "type": "BUY",
        "ticker": ticker,
        "name": name,
        "price": price,
        "shares": shares,
        "total": total_cost,
        "timestamp": datetime.now().isoformat(),
    })

    _save_portfolio(portfolio)
    logger.info(f"買い記録: {name}({ticker}) {shares}株 @ ¥{price:,.0f} = ¥{total_cost:,.0f}")
    return get_portfolio_summary()


def record_sell(ticker: str, name: str, price: float, shares: int) -> dict:
    """
    売り取引を記録する

    Args:
        ticker: ティッカー
        name: 銘柄名
        price: 売却価格
        shares: 売却株数

    Returns:
        更新後のポートフォリオサマリー
    """
    portfolio = _load_portfolio()

    if ticker not in portfolio["holdings"]:
        logger.error(f"保有していない銘柄です: {ticker}")
        return {"error": "保有していない銘柄"}

    holding = portfolio["holdings"][ticker]
    if shares > holding["shares"]:
        logger.error(f"保有数不足: 要求 {shares}株 > 保有 {holding['shares']}株")
        return {"error": "保有数不足"}

    total_revenue = price * shares
    realized_pnl = (price - holding["avg_price"]) * shares

    # 現金を増やす
    portfolio["current_cash"] += total_revenue

    # 実現損益を更新
    portfolio["total_realized_pnl"] = portfolio.get("total_realized_pnl", 0) + realized_pnl

    # 保有銘柄を更新
    remaining_shares = holding["shares"] - shares
    if remaining_shares > 0:
        portfolio["holdings"][ticker]["shares"] = remaining_shares
    else:
        del portfolio["holdings"][ticker]

    # 取引履歴に追加
    portfolio["trades"].append({
        "type": "SELL",
        "ticker": ticker,
        "name": name,
        "price": price,
        "shares": shares,
        "total": total_revenue,
        "realized_pnl": realized_pnl,
        "timestamp": datetime.now().isoformat(),
    })

    _save_portfolio(portfolio)
    logger.info(f"売り記録: {name}({ticker}) {shares}株 @ ¥{price:,.0f} = ¥{total_revenue:,.0f} (損益: ¥{realized_pnl:,.0f})")
    return get_portfolio_summary()


def get_available_cash() -> float:
    """利用可能な現金残高を取得"""
    portfolio = _load_portfolio()
    return portfolio["current_cash"]


def get_max_investment_per_stock() -> float:
    """1銘柄あたりの最大投資額を計算"""
    portfolio = _load_portfolio()
    total_value = portfolio["current_cash"]
    # 保有銘柄の時価も含める場合はここに追加
    return total_value * (RISK_PARAMS["max_per_stock_pct"] / 100)


def get_holdings() -> dict:
    """現在の保有銘柄を取得"""
    portfolio = _load_portfolio()
    return portfolio.get("holdings", {})


def calculate_recommended_shares(ticker: str, price: float) -> int:
    """
    推奨購入株数を計算する
    投資可能額と1銘柄制限を考慮

    Args:
        ticker: ティッカー
        price: 現在の株価

    Returns:
        推奨株数（100株単位、最低100株）
    """
    available = get_available_cash()
    max_per_stock = get_max_investment_per_stock()
    investable = min(available, max_per_stock)

    if price <= 0 or investable < price:
        return 0

    # 通常の上場株は100株単位
    raw_shares = int(investable / price)
    unit_shares = (raw_shares // 100) * 100

    # 100株未満でも1株単位で買える銘柄もあるが、SBI証券では通常100株単位
    # ただし22万円の予算で高額銘柄は1株も買えない場合がある
    if unit_shares == 0 and raw_shares >= 1:
        # S株（単元未満株）対応: 1株単位
        return raw_shares

    return max(unit_shares, 0)
