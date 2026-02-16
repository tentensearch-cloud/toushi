"""
ニュース監視モジュール
Google News RSSから情報を取得し、Geminiで分析して緊急性の高いニュースを通知する
"""
import os
import time
import json
import logging
import feedparser
import google.generativeai as genai
from datetime import datetime
from config import WATCHLIST, DISCORD_WEBHOOK_URL
from portfolio import get_portfolio_summary
import requests

logger = logging.getLogger(__name__)

# Gemini API設定
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-2.0-flash')  # 最新モデルを使用

# ニュース履歴ファイル（重複通知防止）
NEWS_HISTORY_FILE = os.path.join(os.path.dirname(__file__), "news_history.json")

def _load_news_history() -> set:
    if os.path.exists(NEWS_HISTORY_FILE):
        try:
            with open(NEWS_HISTORY_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except:
            pass
    return set()

def _save_news_history(history: set):
    try:
        # 最新1000件のみ保持
        history_list = list(history)[-1000:]
        with open(NEWS_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history_list, f)
    except Exception as e:
        logger.error(f"ニュース履歴保存エラー: {e}")

def fetch_rss_news(query: str) -> list:
    """Google News RSSからニュースを取得"""
    encoded_query = requests.utils.quote(query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ja&gl=JP&ceid=JP:ja"
    feed = feedparser.parse(rss_url)
    return feed.entries

def analyze_news_with_gemini(entry, portfolio_summary):
    """Geminiでニュースを分析し、売買判断を行う"""
    if not GEMINI_API_KEY:
        return None

    title = entry.title
    link = entry.link
    snippet = entry.get("summary", "")[:500]  # 長すぎる場合はカット
    published = entry.get("published", "")

    # ポートフォリオ情報
    cash = portfolio_summary["current_cash"]
    holdings_text = ""
    if portfolio_summary["holdings"]:
        lines = []
        for h in portfolio_summary["holdings"]:
            lines.append(f"- {h['name']} ({h['ticker']}): {h['shares']}株 保有 (取得単価: {h['avg_price']}円)")
        holdings_text = "\n".join(lines)
    else:
        holdings_text = "特になし"

    prompt = f"""
あなたは私の専属投資アドバイザーです。
以下のニュース記事に基づき、対象銘柄に関する緊急のPTS取引（または翌日成行）の判断を行ってください。

【現在の資産状況】
- 現金残高: {cash}円
- 保有状況:
{holdings_text}

【ニュース記事】
タイトル: {title}
概要: {snippet}
日時: {published}

【指示】
この記事が「暴落リスク（倒産、粉飾、事故等）」または「急騰チャンス（TOB、好決算、提携等）」である場合のみ、以下のフォーマットで出力してください。
静観で良い場合は「静観」とだけ出力してください。
**判定は厳格に行ってください。些細なニュースは無視してください。**

出力フォーマット:
# 🚨 緊急シグナル: {{銘柄名}} ({{コード}})
- 判断: [緊急売り / 緊急買い]
- 理由: (1行で簡潔に)
- 指示:
  - PTS指値目安: {{具体的な断定的な価格または指示}} (例: 終値の-3% / 成行 / 2500円以下なら買い)
  - 数量: {{具体的な株数}}株 (資金{cash}円と保有数を考慮して算出)
"""

    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        if "静観" in text and len(text) < 20:
            return None
        return text
    except Exception as e:
        logger.error(f"Gemini分析エラー: {e}")
        return None

def send_news_alert(news_content: str, link: str):
    """ニュースアラートをDiscordに送信"""
    color = 0xFF0000 if "緊急売り" in news_content else 0xFFD700  # 赤 or 金

    embed = {
        "title": "🚨 市場ニュース緊急速報 (PTS/時間外)",
        "description": news_content,
        "color": color,
        "url": link,
        "footer": {"text": "Gemini AI Market Monitor"},
        "timestamp": datetime.utcnow().isoformat()
    }
    
    payload = {"embeds": [embed]}
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=5)
    except Exception as e:
        logger.error(f"Discord通知エラー: {e}")

def process_news(test_mode=False):
    """
    ニュース監視のメインプロセス
    test_mode=Trueの場合、ダミーニュースでテストを行う
    """
    logger.info("ニュース監視プロセス開始")
    
    portfolio_summary = get_portfolio_summary()
    news_history = _load_news_history()

    # テストモード用ダミーニュース
    if test_mode:
        logger.info("テストモード: ダミーニュースで動作確認を実行します")
        class DummyEntry:
            def __init__(self):
                self.title = "【テスト】トヨタ自動車、画期的な全固体電池の量産開始を発表。株価急騰の可能性"
                self.link = "https://example.com"
                self.summary = "トヨタは本日、夢のエネルギー源とされる全固体電池の量産化に成功したと発表。来月からEVに搭載開始。"
                self.published = datetime.now().isoformat()
            def get(self, key, default=None):
                return getattr(self, key, default)

        dummy_entry = DummyEntry()
        result = analyze_news_with_gemini(dummy_entry, portfolio_summary)
        if result:
            logger.info(f"Gemini分析結果(テスト): {result}")
            send_news_alert(result, dummy_entry.link)
        return

    # 1. 注目銘柄の検索クエリ作成
    queries = ["日本株 暴落", "日本株 急騰", "ストップ高", "ストップ安", "TOB"]
    
    # 監視銘柄（保有＋ウォッチリスト上位）を追加
    count = 0
    for ticker, name in WATCHLIST.items():
        if count < 5: # API制限考慮し、主要5銘柄＋キーワードに絞る
            queries.append(name)
            count += 1
            
    # 全クエリを結合して検索（OR検索）
    # RSS URL長制限があるため、分割して実行するか、代表的なキーワードに絞る
    # ここでは代表的なキーワードと保有株名で検索
    
    targets = []
    # 保有株
    if portfolio_summary["holdings"]:
        for h in portfolio_summary["holdings"]:
            targets.append(h["name"])
    
    # なければウォッチリストからいくつか
    if not targets:
        targets = list(WATCHLIST.values())[:3]
        
    search_query = " OR ".join(targets + ["ストップ高", "業績修正", "自社株買い"])
    
    try:
        entries = fetch_rss_news(search_query)
        logger.info(f"取得ニュース数: {len(entries)}件")
        
        for entry in entries[:5]: # 最新5件のみチェック（APIレート制限対策）
            news_id = entry.link
            if news_id in news_history:
                continue
                
            # ここで判定（すべてGeminiに投げると無料枠制限にかかる可能性があるため、簡易フィルタを入れるのが理想だが
            # ユーザー要望は「随時通知」かつ「Gemini判断」なので、直近の未処理ニュースは投げる）
            
            # 記事の日時チェック（24時間以内か？）
            # RSSのpublished parsedを使うのが正確だが、簡易チェック
            
            result = analyze_news_with_gemini(entry, portfolio_summary)
            # 429エラー等でNoneが返ってきた場合のハンドリングは analyze_news_with_gemini 内でログ出力されるが
            # ここで止めるべきか？ 
            # 現状はログだけ出して次へ行くが、429なら次も失敗する可能性が高い。
            
            # 成功しても失敗しても履歴には入れない？ 
            # 失敗した場合は履歴に入れないほうがいい（リトライしたいから）
            if result is not None:
                news_history.add(news_id)
                if result:
                    logger.info(f"重要ニュース検出: {entry.title}")
                    send_news_alert(result, entry.link)
                else:
                    logger.debug(f"静観: {entry.title}")
            else:
                logger.warning(f"分析スキップ（APIエラー等）: {entry.title}")
                # 429エラーが疑われる場合はループを抜けるのが賢明
                break
                
            time.sleep(10) # APIレート制限対策 (15 RPM -> 4s以上必須。安全を見て10s)
            
        _save_news_history(news_history)
        
    except Exception as e:
        logger.error(f"ニュース処理エラー: {e}")

if __name__ == "__main__":
    # 単体テスト用
    from dotenv import load_dotenv
    load_dotenv()
    process_news(test_mode=True)
