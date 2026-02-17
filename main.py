"""
SBI証券 日本株リアルタイム分析ボット - メインエントリーポイント
再構築版: 東証取引時間内（9:00-15:00）に特化し、テクニカル分析とイベント分析（Gemini）を行う
"""
import sys
import argparse
import logging
from datetime import datetime
import pytz

from config import MARKET_HOURS
import data_fetcher
import screener
import event_analyzer
import notifier
import portfolio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")


def is_market_open() -> bool:
    """東証の取引時間内かチェック（土日祝は休み）"""
    jst = pytz.timezone("Asia/Tokyo")
    now = datetime.now(jst)

    # 土日は休場
    if now.weekday() >= 5:
        return False

    hour, minute = now.hour, now.minute
    current_time = hour * 60 + minute

    # 前場: 9:00 - 11:30
    morning_open = MARKET_HOURS["morning_open"][0] * 60 + MARKET_HOURS["morning_open"][1]
    morning_close = MARKET_HOURS["morning_close"][0] * 60 + MARKET_HOURS["morning_close"][1]
    
    # 後場: 12:30 - 15:00
    afternoon_open = MARKET_HOURS["afternoon_open"][0] * 60 + MARKET_HOURS["afternoon_open"][1]
    afternoon_close = MARKET_HOURS["afternoon_close"][0] * 60 + MARKET_HOURS["afternoon_close"][1]

    # マージン（前後数分）を持たせるかどうか？
    # スケジュール実行なので厳密でなくてよいが、15:05とかに動いてほしくないなら厳密に。
    # ユーザー要望「東証取引時間内に必ず」
    
    return (morning_open <= current_time <= morning_close or
            afternoon_open <= current_time <= afternoon_close)


def run_analysis(force: bool = False):
    """
    メイン分析を実行
    1. 株価データ一括取得
    2. テクニカル分析＆スクリーニング（TOP5選出）
    3. イベント分析（Geminiで期待株抽出）
    4. Discord通知
    """
    logger.info("=" * 60)
    logger.info("分析パイプライン開始")
    logger.info("=" * 60)

    try:
        # 1. データ取得（Screener内で行われるが、明示的にDataFetcherを呼ぶ設計も可）
        # ここではScreenerが内部でfetch_daily_data_batchを呼ぶ
        
        # 2. ポートフォリオ状況
        portfolio_summary = portfolio.get_portfolio_summary()
        logger.info(f"資産状況: ¥{portfolio_summary['total_value']:,.0f}")

        # 3. テクニカル分析
        logger.info("テクニカル分析を実行中...")
        screening_result = screener.screen_all_stocks()
        
        # 4. イベント分析（ニュース＆Gemini）
        logger.info("イベント分析を実行中...")
        event_result = event_analyzer.analyze_upcoming_events()
        
        # 5. 通知
        logger.info("Discord通知を送信中...")
        notifier.send_analysis_report(screening_result, event_result, portfolio_summary)

        logger.info("=" * 60)
        logger.info("分析パイプライン完了")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"分析パイプラインで致命的なエラー: {e}", exc_info=True)
        notifier.send_error_notification(str(e))
        # 異常終了させず、通知を送って終わる


def main():
    parser = argparse.ArgumentParser(description="SBI証券 日本株分析ボット (Simple Ver)")
    parser.add_argument("--force", action="store_true", help="取引時間を無視して強制実行")
    parser.add_argument("--notify", action="store_true", help="(互換用) 無視されます（常に通知）")
    parser.add_argument("--test", action="store_true", help="(互換用) 無視されます")
    
    args = parser.parse_args()

    # 取引時間チェック
    if not args.force:
        if not is_market_open():
            logger.info("現在は東証取引時間外です。処理をスキップします。")
            return

    run_analysis(force=args.force)


if __name__ == "__main__":
    main()
