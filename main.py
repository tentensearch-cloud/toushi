"""
SBI証券 日本株リアルタイム分析ボット - メインエントリーポイント

使い方:
  python main.py              # 通常実行（取引時間チェック付き）
  python main.py --test       # テスト実行（取引時間外でも動作、通知なし）
  python main.py --test --notify  # テスト実行 + Discord通知
  python main.py --summary    # サマリーレポートのみ送信
  python main.py --buy TICKER PRICE SHARES   # 買い取引記録
  python main.py --sell TICKER PRICE SHARES  # 売り取引記録
  python main.py --status     # 現在のポートフォリオ状況表示
"""
import sys
import json
import os
import argparse
import logging
from datetime import datetime
import pytz

from config import MARKET_HOURS, WATCHLIST, DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID, PROCESSED_MESSAGES_FILE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")


def is_market_open() -> bool:
    """東証の取引時間内かチェック"""
    jst = pytz.timezone("Asia/Tokyo")
    now = datetime.now(jst)

    # 土日は休場
    if now.weekday() >= 5:
        return False

    hour, minute = now.hour, now.minute
    current_time = hour * 60 + minute

    morning_open = MARKET_HOURS["morning_open"][0] * 60 + MARKET_HOURS["morning_open"][1]
    morning_close = MARKET_HOURS["morning_close"][0] * 60 + MARKET_HOURS["morning_close"][1]
    afternoon_open = MARKET_HOURS["afternoon_open"][0] * 60 + MARKET_HOURS["afternoon_open"][1]
    afternoon_close = MARKET_HOURS["afternoon_close"][0] * 60 + MARKET_HOURS["afternoon_close"][1]

    return (morning_open <= current_time <= morning_close or
            afternoon_open <= current_time <= afternoon_close)


def _load_processed_messages() -> set:
    """処理済みメッセージIDを読み込む"""
    if os.path.exists(PROCESSED_MESSAGES_FILE):
        try:
            with open(PROCESSED_MESSAGES_FILE, "r") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, IOError):
            pass
    return set()


def _save_processed_messages(ids: set):
    """処理済みメッセージIDを保存"""
    try:
        # 最新500件のみ保持
        ids_list = sorted(ids)[-500:]
        with open(PROCESSED_MESSAGES_FILE, "w") as f:
            json.dump(ids_list, f)
    except IOError as e:
        logger.error(f"処理済みメッセージの保存に失敗: {e}")


def process_discord_chat_trades():
    """Discordチャンネルの取引メッセージを処理する"""
    if not DISCORD_BOT_TOKEN or not DISCORD_CHANNEL_ID:
        return

    from trade_parser import process_discord_trades
    from portfolio import record_buy, record_sell, get_portfolio_summary
    from notifier import send_trade_confirmation

    processed_ids = _load_processed_messages()
    trades = process_discord_trades(DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID, minutes_back=10)

    for trade in trades:
        msg_id = trade.get("message_id", "")

        # 既に処理済みのメッセージはスキップ
        if msg_id in processed_ids:
            logger.info(f"メッセージ {msg_id} は処理済み、スキップ")
            continue

        ticker = trade["ticker"]
        name = trade["name"]
        price = trade["price"]
        shares = trade["shares"]
        trade_type = trade["trade_type"]

        logger.info(
            f"Discord取引処理: {trade_type} {name}({ticker}) "
            f"¥{price:,.0f} × {shares}株"
        )

        if trade_type == "BUY":
            result = record_buy(ticker, name, price, shares)
        else:
            result = record_sell(ticker, name, price, shares)

        if "error" not in result:
            portfolio_summary = get_portfolio_summary()
            send_trade_confirmation(trade_type, ticker, name, price, shares, portfolio_summary)
            processed_ids.add(msg_id)
        else:
            logger.error(f"取引処理エラー: {result['error']}")

    _save_processed_messages(processed_ids)


def run_analysis(notify: bool = True, force: bool = False):
    """メイン分析パイプラインを実行"""
    from screener import screen_all_stocks
    from portfolio import get_portfolio_summary
    from notifier import (
        send_analysis_report, send_holdings_alert, send_error_notification,
    )

    logger.info("=" * 60)
    logger.info("分析パイプライン開始")
    logger.info("=" * 60)

    try:
        # 1. Discordチャンネルの取引メッセージを先に処理
        process_discord_chat_trades()

        # 2. ポートフォリオ状況取得
        portfolio_summary = get_portfolio_summary()
        logger.info(
            f"ポートフォリオ: 総資産 ¥{portfolio_summary['total_value']:,.0f}, "
            f"現金 ¥{portfolio_summary['current_cash']:,.0f}, "
            f"損益 ¥{portfolio_summary['total_pnl']:+,.0f}"
        )

        # 3. 全銘柄スクリーニング
        result = screen_all_stocks()

        # 4. 保有銘柄アラート通知
        for alert in result["holdings_alerts"]:
            name = alert.get("name", alert.get("ticker", "?"))
            alert_type = alert.get("alert_type", "?")
            logger.info(f"🚨 保有アラート: {name} - {alert_type}")
            if notify:
                send_holdings_alert(alert, portfolio_summary)

        # 5. 買い候補TOP10を含むメインレポート通知
        top_candidates = result.get("top_candidates", [])
        if top_candidates:
            for i, c in enumerate(top_candidates, 1):
                name = c.get("name", "?")
                price = c.get("current_price", 0)
                score = c.get("score", 0)
                method = c.get("method", "?")
                logger.info(
                    f"  {i}. {name} ¥{price:,.0f} "
                    f"(スコア: {score:+.4f}, {method})"
                )

        if notify:
            # 最新のポートフォリオ状態でレポート送信
            portfolio_summary = get_portfolio_summary()
            send_analysis_report(result, portfolio_summary)

        logger.info("=" * 60)
        logger.info("分析パイプライン完了")
        logger.info("=" * 60)

        return result

    except Exception as e:
        logger.error(f"分析パイプラインでエラー発生: {e}", exc_info=True)
        if notify:
            send_error_notification(str(e))
        raise


def record_trade(trade_type: str, ticker: str, price: float, shares: int):
    """取引を記録"""
    from portfolio import record_buy, record_sell, get_portfolio_summary
    from notifier import send_trade_confirmation

    name = WATCHLIST.get(ticker, ticker)

    # ティッカーに.Tがない場合は付与
    if not ticker.endswith(".T"):
        ticker = ticker + ".T"
        name = WATCHLIST.get(ticker, ticker)

    if trade_type == "BUY":
        result = record_buy(ticker, name, price, shares)
    else:
        result = record_sell(ticker, name, price, shares)

    if "error" in result:
        logger.error(f"取引記録エラー: {result['error']}")
        return

    portfolio_summary = get_portfolio_summary()
    send_trade_confirmation(trade_type, ticker, name, price, shares, portfolio_summary)

    print(f"\n{'='*50}")
    print(f"{'購入' if trade_type == 'BUY' else '売却'}記録完了")
    print(f"銘柄: {name}（{ticker}）")
    print(f"価格: ¥{price:,.1f} × {shares}株 = ¥{price * shares:,.0f}")
    print(f"{'='*50}")
    print(f"現金残高: ¥{portfolio_summary['current_cash']:,.0f}")
    print(f"総資産:   ¥{portfolio_summary['total_value']:,.0f}")
    print(f"損益:     ¥{portfolio_summary['total_pnl']:+,.0f}（{portfolio_summary['total_pnl_pct']:+.2f}%）")
    print(f"{'='*50}")


def show_status():
    """現在のポートフォリオ状況を表示"""
    from portfolio import get_portfolio_summary

    ps = get_portfolio_summary()

    print(f"\n{'='*60}")
    print(f"  SBI証券 ポートフォリオ状況")
    print(f"{'='*60}")
    print(f"  元手:       ¥{ps['initial_capital']:>12,.0f}")
    print(f"  現金:       ¥{ps['current_cash']:>12,.0f}")
    print(f"  保有時価:   ¥{ps['holdings_value']:>12,.0f}")
    print(f"  総資産:     ¥{ps['total_value']:>12,.0f}")
    print(f"  損益:       ¥{ps['total_pnl']:>+12,.0f}（{ps['total_pnl_pct']:+.2f}%）")
    print(f"  確定損益:   ¥{ps['total_realized_pnl']:>+12,.0f}")
    print(f"  取引回数:    {ps['trade_count']}回")
    print(f"{'='*60}")

    if ps["holdings"]:
        print(f"\n  保有銘柄:")
        print(f"  {'銘柄':<16} {'株数':>6} {'取得価格':>10} {'現在価格':>10} {'損益':>10}")
        print(f"  {'-'*54}")
        for h in ps["holdings"]:
            marker = "🟢" if h["pnl_pct"] >= 0 else "🔴"
            print(
                f"  {h['name']:<14} {h['shares']:>6}株 "
                f"¥{h['avg_price']:>9,.0f} ¥{h['current_price']:>9,.0f} "
                f"{marker}{h['pnl_pct']:>+7.2f}%"
            )
    else:
        print(f"\n  保有銘柄なし")

    print()


def main():
    parser = argparse.ArgumentParser(description="SBI証券 日本株分析ボット")
    parser.add_argument("--test", action="store_true", help="テストモード（取引時間チェック無視）")
    parser.add_argument("--notify", action="store_true", help="Discord通知を有効化（--testと併用）")
    parser.add_argument("--summary", action="store_true", help="サマリーレポートのみ送信")
    parser.add_argument("--buy", nargs=3, metavar=("TICKER", "PRICE", "SHARES"),
                        help="買い取引記録（例: --buy 7203.T 2500 100）")
    parser.add_argument("--sell", nargs=3, metavar=("TICKER", "PRICE", "SHARES"),
                        help="売り取引記録（例: --sell 7203.T 2600 100）")
    parser.add_argument("--status", action="store_true", help="ポートフォリオ状況表示")

    args = parser.parse_args()

    # 取引記録
    if args.buy:
        ticker, price, shares = args.buy
        record_trade("BUY", ticker, float(price), int(shares))
        return

    if args.sell:
        ticker, price, shares = args.sell
        record_trade("SELL", ticker, float(price), int(shares))
        return

    # ポートフォリオ状況
    if args.status:
        show_status()
        return

    # サマリーレポート（分析＋通知を統合）
    if args.summary:
        run_analysis(notify=True, force=True)
        return

    # テストモード
    if args.test:
        logger.info("テストモードで実行中...")
        run_analysis(notify=args.notify, force=True)
        return

    # 通常モード: 取引時間チェック
    if not is_market_open():
        logger.info("取引時間外です。スキップします。")
        return

    # 通常分析実行
    run_analysis(notify=True)


if __name__ == "__main__":
    main()
