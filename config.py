"""
SBI証券 日本株分析ボット - 設定ファイル
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ===== Discord設定 =====
DISCORD_WEBHOOK_URL = os.getenv(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1472988441925914825/eIqeM0IFy33mogWJYVv9CtJfOXNhdwBwynSLOF-ITBaC_JuxJwSSsinW8h21tFqRMehg"
)

# Discord Bot設定（チャット取引記録機能用）
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID", "")

# ===== ポートフォリオ設定 =====
INITIAL_CAPITAL = 220000  # 初期資金: 22万円
PORTFOLIO_FILE = os.path.join(os.path.dirname(__file__), "portfolio.json")
SIGNAL_HISTORY_FILE = os.path.join(os.path.dirname(__file__), "signal_history.json")
PROCESSED_MESSAGES_FILE = os.path.join(os.path.dirname(__file__), "processed_messages.json")

# ===== 監視銘柄リスト =====
# NISA成長投資枠対象・流動性の高い日本個別株
# {ティッカー: 銘柄名} 形式
WATCHLIST = {
    # 自動車・輸送
    "7203.T": "トヨタ自動車",
    "7267.T": "ホンダ",
    # 電機・半導体
    "6758.T": "ソニーグループ",
    "6861.T": "キーエンス",
    "6723.T": "ルネサスエレクトロニクス",
    "6857.T": "アドバンテスト",
    "8035.T": "東京エレクトロン",
    # 通信・IT
    "9984.T": "ソフトバンクグループ",
    "9432.T": "NTT",
    "4755.T": "楽天グループ",
    # 金融
    "8306.T": "三菱UFJ FG",
    "8316.T": "三井住友FG",
    "8411.T": "みずほFG",
    # 商社
    "8058.T": "三菱商事",
    "8001.T": "伊藤忠商事",
    # 不動産・建設
    "8830.T": "住友不動産",
    # 医薬
    "4519.T": "中外製薬",
    "4568.T": "第一三共",
    # 消費財
    "9983.T": "ファーストリテイリング",
    "4911.T": "資生堂",
    # 鉄鋼・素材
    "5401.T": "日本製鉄",
    # エンタメ・ゲーム
    "7974.T": "任天堂",
    "9766.T": "コナミグループ",
    # 機械
    "6367.T": "ダイキン工業",
    "6501.T": "日立製作所",
}

# ===== テクニカル分析パラメータ =====
ANALYSIS_PARAMS = {
    # 移動平均線
    "sma_short": 5,       # 短期SMA
    "sma_medium": 25,     # 中期SMA
    "sma_long": 75,       # 長期SMA
    "ema_short": 5,       # 短期EMA
    "ema_medium": 25,     # 中期EMA

    # RSI
    "rsi_period": 14,
    "rsi_oversold": 30,   # 売られすぎ
    "rsi_overbought": 70, # 買われすぎ

    # MACD
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,

    # ボリンジャーバンド
    "bb_period": 20,
    "bb_std": 2,

    # 出来高
    "volume_avg_period": 20,
    "volume_spike_multiplier": 2.0,  # 平均の何倍で急増判定

    # 価格変動率
    "price_change_threshold": 3.0,   # ±%で急騰急落判定
}

# ===== シグナル判定パラメータ =====
SIGNAL_PARAMS = {
    # スコアリングウェイト（合計1.0）
    "weight_ma_cross": 0.20,       # 移動平均クロス
    "weight_rsi": 0.20,            # RSI
    "weight_macd": 0.20,           # MACD
    "weight_bb": 0.15,             # ボリンジャーバンド
    "weight_volume": 0.15,         # 出来高
    "weight_price_momentum": 0.10, # 価格モメンタム

    # シグナル閾値
    "buy_threshold": 0.60,   # 買いシグナル（0.6以上）
    "sell_threshold": -0.60, # 売りシグナル（-0.6以下）
}

# ===== リスク管理 =====
RISK_PARAMS = {
    "take_profit_pct": 5.0,    # 利確ライン: +5%
    "stop_loss_pct": 3.0,      # 損切りライン: -3%
    "max_per_stock_pct": 40.0, # 1銘柄あたり最大投資比率: 40%
    "max_positions": 3,        # 同時保有ポジション上限
}

# ===== データ取得設定 =====
DATA_PARAMS = {
    "intraday_period": "1d",    # イントラデイデータ取得範囲
    "intraday_interval": "5m",  # 5分足
    "daily_period": "3mo",      # 日足データ取得範囲
    "daily_interval": "1d",     # 日足
    "retry_count": 3,           # リトライ回数
    "retry_delay": 2,           # リトライ間隔（秒）
}

# ===== 取引時間（JST） =====
MARKET_HOURS = {
    "morning_open": (9, 0),
    "morning_close": (11, 30),
    "afternoon_open": (12, 30),
    "afternoon_close": (15, 0),
}
