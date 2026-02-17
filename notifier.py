"""
Discord通知モジュール
買い候補TOP10、ポートフォリオ状況をDiscord Webhookで通知する
"""
import logging
import requests
from datetime import datetime
from config import DISCORD_WEBHOOK_URL

logger = logging.getLogger(__name__)

# カラー定義
COLOR_BUY = 0x00FF88        # 緑（買い候補）
COLOR_TAKE_PROFIT = 0xFFD700  # 金（利確アラート）
COLOR_STOP_LOSS = 0xFF6600    # オレンジ（損切りアラート）
COLOR_SUMMARY = 0x5865F2     # 青（サマリー）
COLOR_TRADE = 0x9B59B6       # 紫（取引記録）
COLOR_ERROR = 0xFF0000       # 赤（エラー）

FOOTER_TEXT = "SBI証券 分析ボット | NISA成長投資枠 | 元手: ¥220,000"


def _send_webhook(embeds: list, content: str = None) -> bool:
    """Discord Webhookにメッセージを送信"""
    payload = {}
    if content:
        payload["content"] = content
    if embeds:
        payload["embeds"] = embeds[:10]  # Discord上限: 10 embeds

    try:
        resp = requests.post(
            DISCORD_WEBHOOK_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if resp.status_code == 204:
            logger.info("Discord通知を送信しました")
            return True
        else:
            logger.error(f"Discord通知エラー: {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Discord通知の送信に失敗: {e}")
        return False


def _format_signal_reasons_short(result: dict) -> str:
    """シグナル根拠を短い形式でフォーマット"""
    signals = result.get("signals", {})
    indicators = result.get("indicators", {})
    parts = []

    # MA
    ma = signals.get("ma_cross", 0)
    if ma >= 1:
        parts.append("GC✅")
    elif ma > 0:
        parts.append("MA↑")

    # RSI
    rsi = indicators.get("rsi", 50)
    if rsi <= 30:
        parts.append(f"RSI{rsi:.0f}🟢")
    elif rsi <= 40:
        parts.append(f"RSI{rsi:.0f}")

    # MACD
    macd_sig = signals.get("macd", 0)
    if macd_sig >= 1:
        parts.append("MACD↑")
    elif macd_sig > 0:
        parts.append("MACD+")

    # BB
    bb_sig = signals.get("bb", 0)
    if bb_sig >= 1:
        parts.append("BB底✅")

    # 出来高
    vol_ratio = indicators.get("volume_ratio", 1.0)
    if vol_ratio >= 2.0:
        parts.append(f"Vol{vol_ratio:.1f}x")

    return " | ".join(parts) if parts else "総合スコア"


def send_analysis_report(screening_result: dict, event_result: list, portfolio_summary: dict) -> bool:
    """
    メイン分析レポートを送信
    - ポートフォリオ状況
    - 買い候補TOP5（テクニカル）
    - 期待株TOP5（イベント分析）
    """
    summary = screening_result.get("summary", {})
    # テクニカル分析はTOP5まで
    technical_candidates = screening_result.get("top_candidates", [])[:5]

    embeds = []

    # ===== ポートフォリオ状況 Embed =====
    pnl_emoji = "📈" if portfolio_summary['total_pnl'] >= 0 else "📉"
    holdings_text = "保有銘柄なし"
    if portfolio_summary.get("holdings"):
        holdings_lines = []
        for h in portfolio_summary["holdings"]:
            emoji = "🟢" if h["pnl_pct"] >= 0 else "🔴"
            holdings_lines.append(
                f"{emoji} **{h['name']}** {h['shares']}株 "
                f"| 取得¥{h['avg_price']:,.0f} → 現在¥{h['current_price']:,.0f} "
                f"| {h['pnl_pct']:+.2f}%"
            )
        holdings_text = "\n".join(holdings_lines)

    portfolio_embed = {
        "title": f"{pnl_emoji} ポートフォリオ状況",
        "color": COLOR_SUMMARY,
        "fields": [
            {"name": "💴 元手", "value": f"¥{portfolio_summary['initial_capital']:,.0f}", "inline": True},
            {"name": "💵 現金残高", "value": f"¥{portfolio_summary['current_cash']:,.0f}", "inline": True},
            {"name": "📊 総資産", "value": f"**¥{portfolio_summary['total_value']:,.0f}**", "inline": True},
            {"name": "💰 損益", "value": f"**¥{portfolio_summary['total_pnl']:+,.0f}（{portfolio_summary['total_pnl_pct']:+.2f}%）**", "inline": True},
            {"name": "🏦 確定損益", "value": f"¥{portfolio_summary['total_realized_pnl']:+,.0f}", "inline": True},
            {"name": "📋 取引回数", "value": f"{portfolio_summary['trade_count']}回", "inline": True},
            {"name": "📈 保有銘柄", "value": holdings_text[:1024], "inline": False},
        ],
        "footer": {"text": FOOTER_TEXT},
        "timestamp": datetime.utcnow().isoformat(),
    }
    embeds.append(portfolio_embed)

    # ===== テクニカルTOP5 Embed =====
    if technical_candidates:
        candidates_lines = []
        for i, c in enumerate(technical_candidates, 1):
            name = c.get("name", c.get("ticker", "?"))
            ticker = c.get("ticker", "?")
            price = c.get("current_price", 0)
            score = c.get("score", 0)
            method = c.get("method", "?")
            est_cost = c.get("estimated_cost", 0)
            reasons = _format_signal_reasons_short(c)
            method_icon = "📦" if "単元" in method else "🔹"

            candidates_lines.append(
                f"**{i}. {name} ({ticker})**\n"
                f"　Current: ¥{price:,.0f} | Score: {score:+.4f}\n"
                f"　{method_icon} {method} (¥{est_cost:,.0f})\n"
                f"　📊 {reasons}"
            )

        buy_embed = {
            "title": f"📈 テクニカル有望株 TOP5 ({summary.get('data_available', 0)}銘柄中)",
            "description": "\n\n".join(candidates_lines),
            "color": COLOR_BUY,
        }
        embeds.append(buy_embed)
    else:
        no_tech_embed = {
            "title": "📈 テクニカル有望株",
            "description": "現在、テクニカル分析で強い買いシグナルが出ている銘柄はありません。",
            "color": COLOR_SUMMARY,
        }
        embeds.append(no_tech_embed)

    # ===== イベント期待株TOP5 Embed =====
    if event_result:
        event_lines = []
        for i, e in enumerate(event_result[:5], 1): # TOP5
            name = e.get("name", "?")
            ticker = e.get("ticker", "?")
            reason = e.get("reason", "詳細不明")
            # score = e.get("score", "?") # 表示しないか、必要なら追加

            event_lines.append(
                f"**{i}. {name} ({ticker})**\n"
                f"　💡 {reason}"
            )
        
        event_embed = {
            "title": "✨ 直近の期待材料アリ企業 (Gemini分析)",
            "description": "\n\n".join(event_lines),
            "color": 0xFF00FF, # Magenta
            "footer": {"text": "※ニュース分析結果は1時間キャッシュされます"},
            "timestamp": datetime.utcnow().isoformat(),
        }
        embeds.append(event_embed)
    else:
        # イベントなしの場合は特に表示しないか、「特になし」を表示するか。
        # ユーザーは「教えてください」と言っているので、「不明」を表示する。
        no_event_embed = {
            "title": "✨ 期待材料アリ企業",
            "description": "現在、特筆すべき期待材料は見つかりませんでした（または分析エラー）。",
            "color": COLOR_SUMMARY,
        }
        embeds.append(no_event_embed)

    return _send_webhook(embeds)


def send_holdings_alert(alert: dict, portfolio_summary: dict) -> bool:
    """保有銘柄の利確/損切りアラートを通知"""
    ticker = alert.get("ticker", "")
    name = alert.get("name", ticker)
    alert_type = alert.get("alert_type", "")
    price = alert.get("current_price", 0)
    pnl_pct = alert.get("pnl_pct", 0)
    holding = alert.get("holding", {})

    if alert_type == "TAKE_PROFIT":
        title = f"🏆 利確ライン到達！: {name}（{ticker}）"
        color = COLOR_TAKE_PROFIT
        desc = f"目標の+{RISK_PARAMS['take_profit_pct']}%に到達！利益確定を検討してください。"
    else:
        title = f"⚠️ 損切りライン到達: {name}（{ticker}）"
        color = COLOR_STOP_LOSS
        desc = f"損切りラインの-{RISK_PARAMS['stop_loss_pct']}%に到達。売却を検討してください。"

    from config import RISK_PARAMS

    embed = {
        "title": title,
        "description": desc,
        "color": color,
        "fields": [
            {"name": "現在価格", "value": f"¥{price:,.1f}", "inline": True},
            {"name": "取得価格", "value": f"¥{holding.get('avg_price', 0):,.1f}", "inline": True},
            {"name": "含み損益", "value": f"{pnl_pct:+.2f}%", "inline": True},
            {"name": "保有株数", "value": f"{holding.get('shares', '?')}株", "inline": True},
            {"name": "💰 現金残高", "value": f"¥{portfolio_summary['current_cash']:,.0f}", "inline": True},
            {"name": "📊 総資産", "value": f"¥{portfolio_summary['total_value']:,.0f}", "inline": True},
        ],
        "footer": {"text": FOOTER_TEXT},
        "timestamp": datetime.utcnow().isoformat(),
    }

    return _send_webhook([embed])


def send_trade_confirmation(trade_type: str, ticker: str, name: str,
                            price: float, shares: int, portfolio_summary: dict) -> bool:
    """取引記録の確認通知"""
    total = price * shares
    emoji = "🟢 購入記録" if trade_type == "BUY" else "🔴 売却記録"
    color = COLOR_BUY if trade_type == "BUY" else COLOR_STOP_LOSS

    embed = {
        "title": f"{emoji}: {name}（{ticker}）",
        "color": color,
        "fields": [
            {"name": "💹 価格", "value": f"¥{price:,.1f}", "inline": True},
            {"name": "📦 株数", "value": f"{shares}株", "inline": True},
            {"name": "💰 合計", "value": f"¥{total:,.0f}", "inline": True},
            {"name": "💵 現金残高", "value": f"**¥{portfolio_summary['current_cash']:,.0f}**", "inline": True},
            {"name": "📊 総資産", "value": f"**¥{portfolio_summary['total_value']:,.0f}**", "inline": True},
            {"name": "📈 損益", "value": f"**¥{portfolio_summary['total_pnl']:+,.0f}（{portfolio_summary['total_pnl_pct']:+.2f}%）**", "inline": True},
        ],
        "footer": {"text": FOOTER_TEXT},
        "timestamp": datetime.utcnow().isoformat(),
    }

    return _send_webhook([embed])


def send_error_notification(error_msg: str) -> bool:
    """エラー通知"""
    embed = {
        "title": "❌ 分析ボットエラー",
        "description": f"```\n{error_msg[:2000]}\n```",
        "color": COLOR_ERROR,
        "timestamp": datetime.utcnow().isoformat(),
    }
    return _send_webhook([embed])
