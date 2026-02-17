"""
イベント分析モジュール
各銘柄のニュースを収集し、Geminiを使用して「直近で期待される発表」がある企業を抽出する
API制限を考慮し、結果は1時間キャッシュする
"""
import os
import json
import logging
import feedparser
import time
from datetime import datetime, timedelta
import google.generativeai as genai
from config import WATCHLIST

logger = logging.getLogger(__name__)

# キャッシュファイル
EVENT_CACHE_FILE = os.path.join(os.path.dirname(__file__), "event_cache.json")
CACHE_DURATION_HOURS = 1

# Gemini API設定
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-2.0-flash') # または gemini-pro


def _load_cache() -> dict | None:
    """キャッシュを読み込む（有効期限内のみ）"""
    if os.path.exists(EVENT_CACHE_FILE):
        try:
            with open(EVENT_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                timestamp = datetime.fromisoformat(data["timestamp"])
                if datetime.now() - timestamp < timedelta(hours=CACHE_DURATION_HOURS):
                    return data["result"]
        except Exception:
            pass
    return None


def _save_cache(result: list):
    """結果をキャッシュ保存"""
    try:
        data = {
            "timestamp": datetime.now().isoformat(),
            "result": result
        }
        with open(EVENT_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"イベントキャッシュ保存エラー: {e}")


def fetch_company_news(ticker: str, name: str) -> list:
    """企業のニュースをGoogle News RSSから取得"""
    # 検索クエリ: 企業名 + (決算 OR 発表 OR 提携 OR 新製品)
    query = f"{name} (決算 OR 発表 OR 提携 OR 新製品)"
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=ja&gl=JP&ceid=JP:ja"
    
    try:
        feed = feedparser.parse(rss_url)
        news_items = []
        for entry in feed.entries[:3]: # 最新3件のみ
            news_items.append(f"- {entry.title} ({entry.published})")
        return news_items
    except Exception as e:
        logger.warning(f"[{name}] ニュース取得エラー: {e}")
        return []


def analyze_upcoming_events() -> list:
    """
    全監視銘柄のニュースを分析し、期待値の高い企業TOP5を返す
    """
    # キャッシュチェック
    cached_result = _load_cache()
    if cached_result:
        logger.info("イベント分析: キャッシュを使用します")
        return cached_result

    if not GEMINI_API_KEY:
        logger.warning("Gemini APIキーが設定されていません。イベント分析をスキップします。")
        return []

    logger.info("イベント分析: 新規分析を開始します...")
    
    all_news_text = ""
    valid_count = 0

    # 全銘柄のニュース収集（直列だと遅いが、頻度が低いので一旦許容。必要なら並列化）
    # 25銘柄 * 1秒 = 25秒程度
    for ticker, name in WATCHLIST.items():
        news = fetch_company_news(ticker, name)
        if news:
            all_news_text += f"\n【{name} ({ticker})】\n" + "\n".join(news)
            valid_count += 1
        time.sleep(0.5) # RSS制限回避

    if valid_count == 0:
        return []

    # Gemini プロンプト
    prompt = f"""
あなたはプロの株式アナリストです。
以下の各企業の最近のニュースから、「今後株価上昇が期待される重要な発表やイベント（決算、新製品、提携、上方修正など）」が控えている、または期待される企業を分析してください。

【分析対象ニュース】
{all_news_text}

【指示】
1. 上記ニュースに基づき、期待値が高い順に最大5社を選定してください。
2. 各企業について、以下のJSON形式のリストで出力してください。Markdownのコードブロックは不要です。
3. 該当企業がない場合は空リスト [] を返してください。

出力形式:
[
  {{
    "ticker": "銘柄コード",
    "name": "企業名",
    "reason": "期待される理由やイベント内容（簡潔に）",
    "score": 1〜10の期待度スコア
  }},
  ...
]
"""

    try:
        response = model.generate_content(prompt)
        content = response.text.strip()
        
        # JSON部分の抽出（Markdownなどを除去）
        if "```json" in content:
            content = content.replace("```json", "").replace("```", "")
        elif "```" in content:
            content = content.replace("```", "")
            
        result = json.loads(content)
        
        # 検証と整形
        final_result = []
        for item in result:
            if isinstance(item, dict) and "ticker" in item and "name" in item:
                final_result.append(item)
        
        # 保存
        _save_cache(final_result)
        logger.info(f"イベント分析完了: {len(final_result)}社選定")
        return final_result

    except Exception as e:
        logger.error(f"Gemini分析エラー: {e}")
        return []
