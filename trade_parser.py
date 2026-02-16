"""
Discord取引メッセージ解析モジュール
Discordチャンネルのメッセージを読み取り、取引指示を解析する

対応メッセージ例:
  - "トヨタの株を2500円で100株購入した"
  - "ソニーを3200円で購入"
  - "7203.T 2500円 100株 買い"
  - "8306 1800円 売却"
  - "三菱UFJ 1850円 200株 購入"
"""
import re
import logging
import requests
from datetime import datetime, timedelta, timezone
from config import WATCHLIST

logger = logging.getLogger(__name__)

# ティッカー→名前 と 名前→ティッカー の両方向マッピングを構築
NAME_TO_TICKER = {}
TICKER_SHORT_TO_FULL = {}
for ticker, name in WATCHLIST.items():
    NAME_TO_TICKER[name] = ticker
    # 短縮名も対応（例: "トヨタ" → "トヨタ自動車"）
    # 先頭2〜4文字でもマッチ
    for length in range(2, len(name) + 1):
        short_name = name[:length]
        if short_name not in NAME_TO_TICKER:
            NAME_TO_TICKER[short_name] = ticker
    # ティッカー番号のみでもマッチ（例: "7203" → "7203.T"）
    short_ticker = ticker.replace(".T", "")
    TICKER_SHORT_TO_FULL[short_ticker] = ticker
    TICKER_SHORT_TO_FULL[ticker] = ticker


def parse_trade_message(message: str) -> dict | None:
    """
    取引メッセージを解析する

    Args:
        message: Discord メッセージ文字列

    Returns:
        {"ticker": str, "name": str, "price": float, "shares": int, "trade_type": "BUY"|"SELL"}
        解析失敗時は None
    """
    message = message.strip()
    if not message:
        return None

    # 取引タイプ判定
    trade_type = None
    buy_keywords = ["購入", "買い", "買った", "買う", "購入した"]
    sell_keywords = ["売却", "売り", "売った", "売る", "売却した"]

    for keyword in buy_keywords:
        if keyword in message:
            trade_type = "BUY"
            break
    if trade_type is None:
        for keyword in sell_keywords:
            if keyword in message:
                trade_type = "SELL"
                break
    if trade_type is None:
        return None  # 取引関連メッセージではない

    # 価格の抽出（"2500円", "¥2500", "2,500円" など）
    price_patterns = [
        r'[¥￥]?\s*([\d,]+(?:\.\d+)?)\s*円',
        r'[¥￥]\s*([\d,]+(?:\.\d+)?)',
        r'@\s*([\d,]+(?:\.\d+)?)',
    ]
    price = None
    for pattern in price_patterns:
        match = re.search(pattern, message)
        if match:
            price = float(match.group(1).replace(",", ""))
            break

    if price is None or price <= 0:
        return None

    # 株数の抽出（"100株", "100" など）
    shares = 1  # デフォルト1株（S株対応）
    shares_patterns = [
        r'(\d+)\s*株',
        r'(\d+)\s*(?:株|かぶ)',
    ]
    for pattern in shares_patterns:
        match = re.search(pattern, message)
        if match:
            shares = int(match.group(1))
            break

    # 銘柄の特定
    ticker = None
    name = None

    # まずティッカーコードで検索（"7203.T", "7203" など）
    ticker_match = re.search(r'(\d{4})(?:\.T)?', message)
    if ticker_match:
        short_ticker = ticker_match.group(1)
        if short_ticker in TICKER_SHORT_TO_FULL:
            ticker = TICKER_SHORT_TO_FULL[short_ticker]
            name = WATCHLIST.get(ticker, ticker)

    # ティッカーが見つからなければ銘柄名で検索
    if ticker is None:
        # 長い名前から順にマッチ（部分一致を優先）
        sorted_names = sorted(NAME_TO_TICKER.keys(), key=len, reverse=True)
        for candidate_name in sorted_names:
            if candidate_name in message and len(candidate_name) >= 2:
                ticker = NAME_TO_TICKER[candidate_name]
                name = WATCHLIST.get(ticker, ticker)
                break

    if ticker is None:
        return None

    return {
        "ticker": ticker,
        "name": name,
        "price": price,
        "shares": shares,
        "trade_type": trade_type,
    }


def fetch_discord_messages(bot_token: str, channel_id: str,
                           minutes_back: int = 10) -> list[dict]:
    """
    Discord Bot APIを使ってチャンネルの最近のメッセージを取得する

    Args:
        bot_token: Discord Bot Token
        channel_id: チャンネルID
        minutes_back: 何分前からのメッセージを取得するか

    Returns:
        メッセージのリスト
    """
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"Bot {bot_token}",
    }
    params = {
        "limit": 20,
    }

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        if resp.status_code != 200:
            logger.error(f"Discordメッセージ取得エラー: {resp.status_code} - {resp.text}")
            return []

        messages = resp.json()

        # 指定時間内のメッセージのみフィルタ
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes_back)
        recent_messages = []
        for msg in messages:
            # Bot自身のメッセージは無視
            if msg.get("author", {}).get("bot", False):
                continue
            msg_time = datetime.fromisoformat(msg["timestamp"].replace("Z", "+00:00"))
            if msg_time >= cutoff:
                recent_messages.append(msg)

        logger.info(f"直近{minutes_back}分のユーザーメッセージ: {len(recent_messages)}件")
        return recent_messages

    except Exception as e:
        logger.error(f"Discordメッセージ取得に失敗: {e}")
        return []


def process_discord_trades(bot_token: str, channel_id: str,
                           minutes_back: int = 10) -> list[dict]:
    """
    Discordの最近のメッセージから取引指示を解析・実行する

    Returns:
        処理された取引のリスト
    """
    if not bot_token or not channel_id:
        logger.info("Discord Bot Token/チャンネルIDが未設定。メッセージ取引は無効。")
        return []

    messages = fetch_discord_messages(bot_token, channel_id, minutes_back)
    processed_trades = []

    for msg in messages:
        content = msg.get("content", "")
        trade = parse_trade_message(content)

        if trade is not None:
            logger.info(
                f"取引メッセージ検出: {trade['trade_type']} "
                f"{trade['name']}({trade['ticker']}) "
                f"¥{trade['price']:,.0f} × {trade['shares']}株"
            )
            trade["message_id"] = msg.get("id", "")
            trade["author"] = msg.get("author", {}).get("username", "unknown")
            trade["timestamp"] = msg.get("timestamp", "")
            processed_trades.append(trade)

    return processed_trades
