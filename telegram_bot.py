# telegram_bot.py — Telegram bot front-end for the Trade It signal pipeline.
# Run: python telegram_bot.py  (requires BOT_TOKEN, GROQ_API_KEY or GEMINI_API_KEY in .env)

import os
import sys
import logging
import re
import asyncio
import uuid
from html import escape

from dotenv import load_dotenv
from telegram import (
    Update,
    BotCommand,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

# Add signal_bot package to path so sibling modules import cleanly
sys.path.insert(0, os.path.dirname(__file__))
from src.data_fetcher import fetch_all_timeframes, fetch_fundamentals, clear_cache
from src.indicators import compute_all, latest_values
from src.signal_engine import generate_signal
from src.confluence import compute_confluence
from src.chat_engine import chat, get_provider, provider_label
from src import config as cfg

# News sentiment module — optional; bot degrades gracefully if unavailable
try:
    from src.sentiment import fetch_news_sentiment
    _SENTIMENT_AVAILABLE = True
except ImportError:
    _SENTIMENT_AVAILABLE = False
    print("[telegram_bot] sentiment.py not found or dependencies missing — news sentiment disabled.")

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# Shorthand used everywhere instead of typing ParseMode.HTML each time
HTML = ParseMode.HTML


# ── Ticker resolution (imported from shared module) ──────────────────────────
from ticker_utils import resolve_ticker, ticker_currency, market_label


# ── Per-user state ────────────────────────────────────────────────────────────
# Each user gets an isolated dict; no shared mutable state between users.

USER_STATE: dict = {}


def get_state(user_id: int) -> dict:
    """Return (and lazily create) the state dict for a given user."""
    if user_id not in USER_STATE:
        USER_STATE[user_id] = {
            "mode":        "idle",     # idle | fetching | chat | waiting_ticker | set_capital | set_risk
            "token":       None,       # UUID of the currently-owned fetch task (race-condition guard)
            "last_signal": None,       # plain-text signal summary for AI context injection
            "last_result": None,       # ConfluenceResult object from the most recent analysis
            "last_ticker": None,       # last analysed ticker string
            "history":     [],         # AI chat message history (kept to last 20 messages = 10 turns)
            "active_task": None,       # asyncio.Task currently fetching data (if any)
        }
    return USER_STATE[user_id]


def cancel_active_task(user_id: int) -> bool:
    """
    Cancel any running fetch task for this user and reset mode to idle.
    Returns True if a task was actively cancelled, False if nothing was running.
    """
    state = get_state(user_id)
    task: asyncio.Task | None = state.get("active_task")
    state["active_task"] = None
    state["mode"] = "idle"
    if task and not task.done():
        task.cancel()
        return True
    return False


async def _safe_edit(msg, text: str, **kwargs) -> bool:
    """
    Attempt to edit a Telegram message. Returns True on success, False otherwise.
    Never raises — swallows all Telegram API errors silently.
    Used everywhere instead of raw msg.edit_text() to avoid 400 Bad Request crashes
    caused by race conditions (e.g. user cancels while fetch completes).
    """
    try:
        await msg.edit_text(text, **kwargs)
        return True
    except Exception:
        return False


# ── Keyboards ─────────────────────────────────────────────────────────────────
# Main persistent keyboard — always visible at the bottom of the chat
MAIN_KB = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📈 Analyse"), KeyboardButton("🔍 Scan Watchlist")],
        [KeyboardButton("💬 Chat"),    KeyboardButton("⚙️ Settings")],
    ],
    resize_keyboard=True,
    is_persistent=True,
)

# Shown while a fetch is in progress — replaces MAIN_KB so the only action is Cancel
CANCEL_KB = ReplyKeyboardMarkup(
    [[KeyboardButton("❌ Cancel")]],
    resize_keyboard=True,
    is_persistent=True,
)


# Words that match the ticker regex but should be treated as conversation, not stock symbols
_NOT_TICKERS = {
    "hi", "hey", "hello", "hii", "helo", "heyy", "heya",
    "ok", "okay", "k", "yes", "no", "nope", "yep", "sure",
    "thanks", "thank", "thx", "ty", "np",
    "bye", "good", "great", "nice", "cool", "wow",
    "what", "why", "how", "who", "when", "where",
    "help", "start", "stop", "go", "run",
    "lol", "haha", "hmm", "oh", "ah",
}


def signal_inline_kb(ticker: str) -> InlineKeyboardMarkup:
    """Inline buttons shown below each signal result."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🤔 Explain",        callback_data=f"explain:{ticker}"),
            InlineKeyboardButton("🔄 Refresh",         callback_data=f"refresh:{ticker}"),
        ],
        [
            InlineKeyboardButton("🔔 Set Alert",       callback_data=f"alert:{ticker}"),
            InlineKeyboardButton("📊 All Timeframes",  callback_data=f"alltf:{ticker}"),
        ],
    ])


# Inline buttons for the Settings panel
SETTINGS_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("💰 Set Capital",    callback_data="set:capital")],
    [InlineKeyboardButton("📉 Set Risk %",     callback_data="set:risk")],
    [InlineKeyboardButton("📋 View Watchlist", callback_data="set:watchlist")],
])


# ── Signal pipeline ───────────────────────────────────────────────────────────

def run_signal(ticker: str, include_sentiment: bool = True) -> tuple[str, object]:
    """
    Run the multi-agent pipeline for one ticker (or legacy fallback).

    Returns (html_string, ConfluenceResult).
    Raises ValueError if the ticker is not found on Yahoo Finance.
    """
    try:
        from orchestrator import analyse_sync, analyse_scan
        if include_sentiment:
            result = analyse_sync(ticker, include_sentiment=True)
        else:
            # Scan mode: Python-only, zero LLM calls
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(analyse_scan(ticker))
            finally:
                loop.close()
        return format_signal_html(result), result

    except ValueError:
        # Ticker not found — let it propagate to do_analyse / do_scan
        raise

    except (ImportError, RuntimeError) as e:
        log.warning("Orchestrator unavailable (%s), using legacy pipeline", e)
        ticker = resolve_ticker(ticker)

        data = fetch_all_timeframes(ticker)

        if all(df is None for df in data.values()):
            raise ValueError(ticker)

        signals = {}
        for tf_name, df in data.items():
            if df is None:
                signals[tf_name] = None
                continue
            enriched = compute_all(df)
            vals     = latest_values(enriched)
            signals[tf_name] = generate_signal(tf_name, vals)

        fundamentals = fetch_fundamentals(ticker)

        news_sentiment = None
        if include_sentiment and _SENTIMENT_AVAILABLE:
            news_sentiment = fetch_news_sentiment(ticker)

        result = compute_confluence(ticker, signals, fundamentals, news_sentiment)
        clear_cache()
        return format_signal_html(result), result


def format_signal_html(result) -> str:
    """
    Format a ConfluenceResult as Telegram-safe HTML following the CLAUDE.md output format:
      1. Six-perspective summary table (signal + confidence)
      2. Bull case vs bear case + which wins
      3. Recommendation: BUY / SELL / HOLD / NO TRADE
      4. Trade levels: entry, stop, targets, position size (if actionable)
      5. Overall confidence + top 3 mind-changers
      6. One-line caveat

    All dynamic content is html.escape()'d. Uses only <b>, <i>, <code> tags.
    Currency symbol derived from ticker suffix (Rs. / $ / A$ / £).
    """
    d_emoji = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}
    v_emoji = {"BUY": "✅", "SELL": "🚫", "HOLD": "⏸", "NO TRADE": "⛔"}
    c_icon  = {"HIGH": "●", "MEDIUM": "◑", "LOW": "○"}   # confidence dots

    cur = ticker_currency(result.ticker)
    mkt = market_label(result.ticker)
    unit = "units" if "-USD" in result.ticker.upper() else "shares"

    # Human-readable signal words
    sig_word  = {"BULLISH": "Looks Good 📈", "BEARISH": "Looks Weak 📉", "NEUTRAL": "Mixed ➡️"}
    conf_word = {"HIGH": "Strong", "MEDIUM": "Moderate", "LOW": "Weak"}

    # Check if ALL timeframes had no data (partial result — fundamentals/news only)
    no_chart_data = all(
        sig is None for sig in result.timeframe_signals.values()
    )

    lines = [
        f"<b>{escape(result.ticker)}</b>  <i>({mkt})</i>",
    ]
    if no_chart_data:
        lines += [
            "",
            "⚠️ <i>No live chart data found for this ticker. "
            "The Charts and Stats rows below are based on fundamentals and news only. "
            "If this looks wrong, try adding <code>.NS</code> or the correct exchange suffix.</i>",
        ]
    lines += [
        "",
        # ── 1. What each angle says ───────────────────────────────────────────
        "<b>📋 What Each Angle Says</b>",
        "<code>Angle            View           Confidence</code>",
        "<code>──────────────────────────────────────────</code>",
    ]

    persp_labels = [
        ("technical",    "📈 Charts      "),
        ("fundamental",  "📊 Financials  "),
        ("macro",        "🌍 Big Picture "),
        ("sentiment",    "📰 News        "),
        ("quantitative", "🔢 Stats       "),
        ("risk",         "🛡 Risk Check  "),
    ]
    for key, label in persp_labels:
        p = result.perspectives.get(key)
        if p:
            view = sig_word.get(p.signal, "Mixed ➡️")
            conf = conf_word.get(p.confidence, "Weak")
            lines.append(f"<code>{label}</code>  {view:<18}  {conf}")

    # ── News detail ──────────────────────────────────────────────────────────
    sent_persp = result.perspectives.get("sentiment")
    if sent_persp and sent_persp.points:
        lines += ["", "<b>📰 Latest News</b>"]
        headline_num = 1
        for pt in sent_persp.points:
            # Summary lines (mood + count) stay as plain italic text
            # Headline lines start with 📈/📉/➡️ — number those
            if pt.strip().startswith(("📈", "📉", "➡️")):
                lines.append(f"<b>{headline_num}.</b> <i>{escape(pt.strip())}</i>")
                headline_num += 1
            else:
                lines.append(f"<i>{escape(pt)}</i>")

    lines += [
        "",
        # ── 2. Bull vs Bear ───────────────────────────────────────────────────
        "<b>⚖️ Bull vs Bear</b>",
        f"🐂 <b>Why it could go UP:</b>",
        f"<i>{escape(result.bull_case)}</i>",
        "",
        f"🐻 <b>Why it could go DOWN:</b>",
        f"<i>{escape(result.bear_case)}</i>",
        "",
        f"<b>🏆 Verdict: {escape(result.winning_case)}</b>",
        "",
        # ── 3. Recommendation ────────────────────────────────────────────────
        f"{v_emoji.get(result.final_verdict, '❓')} "
        f"<b>Action: {result.final_verdict}</b>",
    ]

    # ── 4. Trade levels ──────────────────────────────────────────────────────
    if result.final_verdict in ("BUY", "SELL") and result.best_entry:
        lines += [
            "",
            f"📍 <b>Buy around:</b>   {cur}{result.best_entry:,.2f}",
            f"🛑 <b>Exit if it hits:</b> {cur}{result.best_stop:,.2f}  <i>(your safety stop)</i>",
            f"🎯 <b>Target 1:</b>  {cur}{result.best_target_1:,.2f}  <i>(take some profit here)</i>",
            f"🎯 <b>Target 2:</b>  {cur}{result.best_target_2:,.2f}  <i>(let the rest run)</i>",
        ]
        if result.position_size:
            lines += [
                "",
                f"📦 <b>How many shares:</b> {result.position_size} {unit}",
                f"💰 <b>Money needed:</b> {cur}{result.position_value:,.0f}",
                f"⚠ <b>Max you could lose:</b> {cur}{result.risk_amount:,.0f}  "
                f"<i>({cfg.RISK['risk_pct_per_trade']*100:.1f}% of your capital)</i>",
            ]

    # Warnings
    if result.notes:
        lines.append("")
        for note in result.notes:
            lines.append(f"⚠ <i>{escape(note)}</i>")

    # ── 5. Confidence + what to watch ────────────────────────────────────────
    lines += [
        "",
        f"📊 <b>How confident are we: {result.overall_confidence}</b>",
        "",
        "<b>👀 Watch for these to change the view:</b>",
    ]
    for i, mc in enumerate(result.mind_changers[:3], 1):
        lines.append(f"  {i}. {escape(mc)}")

    # ── 6. Caveat ────────────────────────────────────────────────────────────
    lines += [
        "",
        "<i>⚠ This is analysis only — not financial advice. Always do your own "
        "research before trading. A human must make and execute every decision.</i>",
    ]

    return "\n".join(lines)


def format_signal_plain(result) -> str:
    """
    Compact plain-text summary injected as context into the AI chat engine.
    Includes the six perspectives, adversarial step, and per-timeframe detail
    so the AI can explain the signal fully without re-running the analysis.
    Also used by the 'All Timeframes' inline button to surface TF-level data.
    """
    cur  = ticker_currency(result.ticker)
    unit = "units" if "-USD" in result.ticker.upper() else "shares"
    lines = [
        f"Ticker: {result.ticker}  ({market_label(result.ticker)})",
        f"Direction: {result.overall_direction} ({result.confluence_level})",
        f"Verdict: {result.final_verdict}  |  Confidence: {result.overall_confidence}",
        "",
        "Six perspectives:",
    ]
    persp_order = ["technical", "fundamental", "macro", "sentiment", "quantitative", "risk"]
    for key in persp_order:
        p = result.perspectives.get(key)
        if p:
            top = p.points[0] if p.points else "—"
            lines.append(f"  {key.title()}: {p.signal} ({p.confidence}) — {top}")
            if key == "sentiment":
                for extra in p.points[1:]:
                    lines.append(f"    {extra}")

    lines += [
        "",
        f"Bull case: {result.bull_case}",
        f"Bear case: {result.bear_case}",
        f"Winner: {result.winning_case}",
    ]

    if result.best_entry:
        lines += [
            "",
            f"Entry: {cur}{result.best_entry:,.2f}",
            f"Stop:  {cur}{result.best_stop:,.2f}  (1.5x ATR)",
            f"T1:    {cur}{result.best_target_1:,.2f}  (2R)",
            f"T2:    {cur}{result.best_target_2:,.2f}  (3R)",
        ]
        if result.position_size:
            lines.append(
                f"Position: {result.position_size} {unit} | "
                f"{cur}{result.position_value:,.0f} | "
                f"Risk: {cur}{result.risk_amount:,.0f}"
            )

    # Per-timeframe detail — parsed by the 'All Timeframes' inline button callback
    tf_order = ["weekly", "daily", "1hour", "15min"]
    tf_lines = []
    for tf in tf_order:
        sig = result.timeframe_signals.get(tf)
        if sig:
            rr = f"  R:R {sig.risk_reward:.1f}:1" if sig.risk_reward else ""
            tf_lines.append(
                f"  {tf}: {sig.direction} ({sig.confidence}){rr}"
            )
    if tf_lines:
        lines += ["", "Timeframe detail:"] + tf_lines

    return "\n".join(lines)


# ── Slash command handlers ────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Welcome message shown on /start or first open."""
    name = escape(update.effective_user.first_name or "there")
    ai   = escape(provider_label())
    await update.message.reply_text(
        f"👋 Hi <b>{name}</b>! I'm <b>Trade It</b> — your global market signal bot.\n\n"
        f"I can analyse <b>any stock, crypto, or index worldwide</b>:\n"
        f"🇮🇳 Indian NSE/BSE · 🇺🇸 US stocks · ₿ Crypto · 🇦🇺 ASX · 🇬🇧 LSE · 🇯🇵 TSE and more\n\n"
        f"Every signal covers 4 timeframes (15m, 1h, daily, weekly) and 6 angles:\n"
        f"Charts · Financials · Big Picture · News · Stats · Risk\n\n"
        f"🤖 AI explanations powered by: <i>{ai}</i>\n\n"
        f"Just type any ticker to get started — e.g. <code>HAL</code>, <code>AAPL</code>, <code>BTC</code> 👇",
        parse_mode=HTML,
        reply_markup=MAIN_KB,
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Full command reference including multi-market ticker format guide."""
    await update.message.reply_text(
        "<b>Trade It — Command Reference</b>\n\n"

        "<b>Signals</b>\n"
        "/analyse <code>TICKER</code> — Signal for any stock/crypto\n"
        "/scan — Scan the full watchlist for BUY/SELL signals\n"
        "/explain — Explain the last signal in plain English\n\n"

        "<b>Settings</b>\n"
        "/setcapital <code>AMOUNT</code> — e.g. <code>/setcapital 500000</code>\n"
        "/setrisk <code>PCT</code> — e.g. <code>/setrisk 1.5</code>\n"
        "/watchlist — View the scan watchlist\n\n"

        "<b>Chat</b>\n"
        "/chat — AI chat mode\n"
        "/done — Exit chat mode\n"
        "/cancel — Cancel any running operation\n\n"

        "<b>Supported Markets</b>\n"
        "🇮🇳 Indian NSE:   <code>HAL</code> or <code>HAL.NS</code>\n"
        "🇮🇳 Indian BSE:   <code>RELIANCE.BO</code>\n"
        "🇺🇸 US stocks:    <code>AAPL</code>  <code>TSLA</code>  <code>NVDA</code>\n"
        "₿  Crypto:       <code>BTC</code>  <code>ETH</code>  <code>SOL</code>\n"
        "🇦🇺 Australia:    <code>CBA.AX</code>  <code>BHP.AX</code>\n"
        "🇬🇧 UK (LSE):     <code>HSBA.L</code>  <code>BP.L</code>\n\n"

        "<i>Tip: just type a ticker directly to analyse it instantly.</i>",
        parse_mode=HTML,
        reply_markup=MAIN_KB,
    )


async def cmd_analyse(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/analyse [TICKER] — analyse a single stock."""
    if not ctx.args:
        # No ticker provided — ask for it
        get_state(update.effective_user.id)["mode"] = "waiting_ticker"
        await update.message.reply_text(
            "Which stock, crypto, or index? Just type the ticker:\n"
            "🇮🇳 Indian: <code>HAL</code>  <code>HDFCBANK</code>  <code>TCS</code>\n"
            "🇺🇸 US: <code>AAPL</code>  <code>NVDA</code>  <code>TSLA</code>\n"
            "₿ Crypto: <code>BTC</code>  <code>ETH</code>  <code>SOL</code>",
            parse_mode=HTML,
        )
        return
    await do_analyse(update, ctx, ctx.args[0])


async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/scan — scan full watchlist."""
    await do_scan(update, ctx)


async def cmd_explain(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/explain — send the last signal to AI for a plain-English breakdown."""
    await do_explain(update, ctx)


async def cmd_setcapital(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/setcapital AMOUNT — update trading capital for position sizing."""
    if not ctx.args:
        await update.message.reply_text("Usage: <code>/setcapital 500000</code>", parse_mode=HTML)
        return
    try:
        amount = float(ctx.args[0].replace(",", ""))
        cfg.RISK["capital"] = amount
        await update.message.reply_text(f"✅ Capital set to Rs.{amount:,.0f}")
    except ValueError:
        await update.message.reply_text("Invalid amount. Example: <code>/setcapital 500000</code>", parse_mode=HTML)


async def cmd_setrisk(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/setrisk PCT — set max risk per trade as a percentage of capital."""
    if not ctx.args:
        await update.message.reply_text("Usage: <code>/setrisk 1.5</code> (percent)", parse_mode=HTML)
        return
    try:
        pct = float(ctx.args[0].strip("%")) / 100
        if pct <= 0 or pct > 0.1:
            await update.message.reply_text("Risk % must be between 0.1% and 10%.")
            return
        cfg.RISK["risk_pct_per_trade"] = pct
        await update.message.reply_text(f"✅ Risk per trade set to {pct*100:.1f}%")
    except ValueError:
        await update.message.reply_text("Invalid. Example: <code>/setrisk 1.5</code>", parse_mode=HTML)


async def cmd_watchlist(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/watchlist — list all tickers in the scan watchlist."""
    if not cfg.WATCHLIST:
        await update.message.reply_text("Your watchlist is empty. Use /add TICKER to add stocks.", reply_markup=MAIN_KB)
        return
    lines = [f"<b>📋 Watchlist ({len(cfg.WATCHLIST)} stocks)</b>\n"]
    for name, ticker in cfg.WATCHLIST.items():
        lines.append(f"  • <code>{escape(ticker)}</code>  <i>({escape(name)})</i>")
    lines += ["", "<i>Use /add TICKER to add · /remove TICKER to remove</i>"]
    await update.message.reply_text("\n".join(lines), parse_mode=HTML, reply_markup=MAIN_KB)


async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/add TICKER — add a ticker to the watchlist."""
    if not ctx.args:
        await update.message.reply_text(
            "Usage: <code>/add TICKER</code>\n"
            "Examples: <code>/add AAPL</code>  <code>/add BTC</code>  <code>/add WIPRO.NS</code>",
            parse_mode=HTML, reply_markup=MAIN_KB,
        )
        return
    raw     = ctx.args[0]
    ticker  = resolve_ticker(raw)
    # Use the raw input as the display name (uppercased, no suffix)
    name    = raw.upper().split(".")[0]
    if ticker in cfg.WATCHLIST.values():
        await update.message.reply_text(
            f"<code>{escape(ticker)}</code> is already in your watchlist.", parse_mode=HTML, reply_markup=MAIN_KB
        )
        return
    cfg.WATCHLIST[name] = ticker
    await update.message.reply_text(
        f"✅ Added <b>{escape(name)}</b> (<code>{escape(ticker)}</code>) to watchlist.\n"
        f"Watchlist now has {len(cfg.WATCHLIST)} stocks.",
        parse_mode=HTML, reply_markup=MAIN_KB,
    )


async def cmd_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/remove TICKER — remove a ticker from the watchlist."""
    if not ctx.args:
        await update.message.reply_text(
            "Usage: <code>/remove TICKER</code>\nExample: <code>/remove HAL</code>",
            parse_mode=HTML, reply_markup=MAIN_KB,
        )
        return
    raw    = ctx.args[0].upper()
    ticker = resolve_ticker(raw)
    # Find by ticker value or name key
    key_to_remove = None
    for k, v in cfg.WATCHLIST.items():
        if v == ticker or k.upper() == raw.split(".")[0]:
            key_to_remove = k
            break
    if key_to_remove:
        removed_ticker = cfg.WATCHLIST.pop(key_to_remove)
        await update.message.reply_text(
            f"🗑 Removed <b>{escape(key_to_remove)}</b> (<code>{escape(removed_ticker)}</code>) from watchlist.\n"
            f"Watchlist now has {len(cfg.WATCHLIST)} stocks.",
            parse_mode=HTML, reply_markup=MAIN_KB,
        )
    else:
        await update.message.reply_text(
            f"<code>{escape(raw)}</code> not found in watchlist. Use /watchlist to see what's in it.",
            parse_mode=HTML, reply_markup=MAIN_KB,
        )


async def cmd_chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/chat — enter AI chat mode for free-form trading questions."""
    get_state(update.effective_user.id)["mode"] = "chat"
    await update.message.reply_text(
        "💬 <b>AI Chat mode.</b>\n\n"
        "Ask me anything — markets, indicators, signal explanations, strategies.\n\n"
        "Type /done or tap <b>📈 Analyse</b> to go back to signals.",
        parse_mode=HTML,
    )


async def cmd_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/done — exit chat mode and clear conversation history."""
    state = get_state(update.effective_user.id)
    state["mode"]    = "idle"
    state["history"] = []
    await update.message.reply_text("Back to signal mode. 📈", reply_markup=MAIN_KB)


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/cancel — cancel any running fetch and clear chat history."""
    user_id   = update.effective_user.id
    cancelled = cancel_active_task(user_id)
    get_state(user_id)["history"] = []
    if cancelled:
        await update.message.reply_text("❌ Cancelled.", reply_markup=MAIN_KB)
    else:
        await update.message.reply_text("Nothing to cancel.", reply_markup=MAIN_KB)


# ── Core action functions ─────────────────────────────────────────────────────

async def do_analyse(update: Update, ctx: ContextTypes.DEFAULT_TYPE, ticker: str):
    """
    Fetch and display a signal for a single ticker.

    - Cancels any previous fetch first (user tapped Analyse again mid-fetch).
    - Issues a UUID token so the completion handler can verify it still owns the message
      (handles the race: cancel arrives while fetch is completing).
    - All I/O runs in asyncio.to_thread() to avoid blocking the event loop.
    """
    user_id = update.effective_user.id
    state   = get_state(user_id)

    cancel_active_task(user_id)   # abort any prior fetch

    # UUID token — only the task that set this token may edit the status message
    token = str(uuid.uuid4())
    state["mode"]  = "fetching"
    state["token"] = token

    msg = await update.message.reply_text(
        f"⏳ Fetching signal for <b>{escape(ticker.upper())}</b>...\n"
        f"<i>Tap ❌ Cancel to stop.</i>",
        parse_mode=HTML,
        reply_markup=CANCEL_KB,
    )

    async def _fetch():
        return await asyncio.wait_for(
            asyncio.to_thread(run_signal, ticker),
            timeout=60,   # news sentiment scoring (FinBERT) adds latency on first run
        )

    task = asyncio.create_task(_fetch())
    state["active_task"] = task

    try:
        text, result = await task

        # Token check: if cancelled or superseded, don't edit the message
        if state.get("mode") == "fetching" and state.get("token") == token:
            state["last_signal"] = format_signal_plain(result)
            state["last_result"] = result
            state["last_ticker"] = result.ticker
            state["mode"]        = "idle"
            state["active_task"] = None

            edited = await _safe_edit(msg, text, parse_mode=HTML,
                                      reply_markup=signal_inline_kb(result.ticker))
            if not edited:
                # Fallback: message was deleted or too old — send fresh
                await update.message.reply_text(text, parse_mode=HTML,
                                                reply_markup=signal_inline_kb(result.ticker))
            await update.message.reply_text("✅ Done.", reply_markup=MAIN_KB)

    except asyncio.CancelledError:
        # User tapped ❌ Cancel — cancel_active_task already notified them
        await _safe_edit(msg, "❌ Cancelled.")

    except asyncio.TimeoutError:
        state["mode"]        = "idle"
        state["active_task"] = None
        await _safe_edit(msg, "⏱ Timed out (60 s). Yahoo Finance may be slow — try again.")
        await update.message.reply_text("Ready.", reply_markup=MAIN_KB)

    except ValueError as e:
        # run_signal raises ValueError(ticker) when no data is found on any timeframe
        state["mode"]        = "idle"
        state["active_task"] = None
        resolved = str(e)   # the resolved ticker string that was tried
        await _safe_edit(
            msg,
            f"❌ <b>Symbol not found: {escape(resolved)}</b>\n\n"
            f"Yahoo Finance returned no price data. The stock may be delisted, "
            f"the symbol may be wrong, or the market is closed.\n\n"
            f"<b>Try these formats:</b>\n"
            f"  Indian NSE: <code>HDFCBANK.NS</code>  <code>HAL.NS</code>  <code>TCS.NS</code>\n"
            f"  US stocks:  <code>AAPL</code>  <code>NVDA</code>  (no suffix needed)\n"
            f"  Crypto:     <code>BTC</code>  <code>ETH</code>  <code>SOL</code>\n"
            f"  Australia:  <code>CBA.AX</code>  <code>BHP.AX</code>",
            parse_mode=HTML,
        )
        await update.message.reply_text("👆 Try a different symbol.", reply_markup=MAIN_KB)

    except Exception as e:
        state["mode"]        = "idle"
        state["active_task"] = None
        log.exception("Error in do_analyse for %s", ticker)
        await _safe_edit(msg, f"❌ Error: {escape(str(e))}", parse_mode=HTML)
        await update.message.reply_text("Ready.", reply_markup=MAIN_KB)


async def do_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Scan every ticker in the watchlist and show a summary table.

    - Each ticker is fetched sequentially (not parallel) to be gentle on Yahoo Finance.
    - Token guard ensures a late-completing scan doesn't overwrite a cancelled message.
    - Falls back to reply_text if the status message can no longer be edited.
    """
    user_id = update.effective_user.id
    state   = get_state(user_id)

    cancel_active_task(user_id)

    token = str(uuid.uuid4())
    state["mode"]  = "fetching"
    state["token"] = token

    msg = await update.message.reply_text(
        f"⏳ Scanning {len(cfg.WATCHLIST)} tickers... this may take a minute.\n"
        f"<i>Tap ❌ Cancel to stop.</i>",
        parse_mode=HTML,
        reply_markup=CANCEL_KB,
    )

    async def _scan():
        results = []
        for name, ticker in cfg.WATCHLIST.items():
            # Check token each iteration — bail early if cancelled or superseded
            if state.get("mode") != "fetching" or state.get("token") != token:
                break
            try:
                # Skip news sentiment during full scans — keeps per-ticker latency low
                _, result = await asyncio.to_thread(run_signal, ticker, False)
                results.append(result)
            except ValueError:
                # Ticker not found on Yahoo Finance — skip silently
                log.warning("Scan: no data for %s (%s), skipping.", name, ticker)
            except Exception:
                # Network error, timeout, etc. — skip and continue
                log.warning("Scan: error fetching %s (%s), skipping.", name, ticker)
        return results

    task = asyncio.create_task(asyncio.wait_for(_scan(), timeout=120))
    state["active_task"] = task

    try:
        results = await task

        # Guard: if cancelled while scanning, discard results
        if state.get("mode") != "fetching" or state.get("token") != token:
            await _safe_edit(msg, "❌ Scan cancelled.")
            return

        state["mode"]        = "idle"
        state["active_task"] = None

        if not results:
            await _safe_edit(msg, "❌ Could not fetch any data. Check your internet connection.")
            await update.message.reply_text("Ready.", reply_markup=MAIN_KB)
            return

        direction_emoji = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}
        verdict_emoji   = {"BUY": "✅",     "SELL": "🚫",   "HOLD": "⏸", "NO TRADE": "⛔"}

        lines = ["<b>Watchlist Scan</b>\n"]
        actionable = []

        for r in results:
            d     = direction_emoji.get(r.overall_direction, "⚪")
            v     = verdict_emoji.get(r.final_verdict, "❓")
            entry = f"Rs.{r.best_entry:,.0f}" if r.best_entry else "—"
            lines.append(
                f"{d} <code>{escape(r.ticker):<14}</code> {v} {r.final_verdict:<10}  {entry}"
            )
            if r.final_verdict in ("BUY", "SELL"):
                actionable.append(r)

        summary = (
            f"\n<b>{len(actionable)} actionable signal(s) found.</b>"
            if actionable else
            "\n<i>No BUY/SELL signals right now.</i>"
        )
        lines.append(summary)

        edited = await _safe_edit(msg, "\n".join(lines), parse_mode=HTML)
        if not edited:
            # Message was deleted — send a fresh one
            await update.message.reply_text("\n".join(lines), parse_mode=HTML)
        await update.message.reply_text("✅ Scan complete.", reply_markup=MAIN_KB)

    except asyncio.CancelledError:
        # cancel_active_task already notified the user
        await _safe_edit(msg, "❌ Scan cancelled.")

    except asyncio.TimeoutError:
        state["mode"]        = "idle"
        state["active_task"] = None
        await _safe_edit(msg, "⏱ Scan timed out (2 min). Try a shorter watchlist.")
        await update.message.reply_text("Ready.", reply_markup=MAIN_KB)


async def do_explain(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Ask the AI to explain the last signal in plain English."""
    state = get_state(update.effective_user.id)
    last  = state.get("last_signal")

    if not last:
        await update.message.reply_text(
            "No signal yet. Run /analyse first.", reply_markup=MAIN_KB
        )
        return

    msg   = await update.message.reply_text("🤔 Thinking...")
    reply = chat(
        "Explain this trading signal in plain language using ONLY the data in the context below. "
        "Focus on: (1) what the final VERDICT is (BUY/SELL/HOLD/NO TRADE) and why, "
        "(2) which case won — bull or bear — and the key evidence for it, "
        "(3) what the trader should specifically watch for to change this view. "
        "Do NOT describe it as bullish or bearish based on the 'Direction' field alone — "
        "the Direction is the raw technical vote, but the Verdict and Winner fields reflect "
        "the full six-perspective conclusion. Keep the explanation to 4–6 sentences.",
        history=state.get("history", []),
        context=last,
    )
    state["history"].append({"role": "user",      "content": "Explain this signal."})
    state["history"].append({"role": "assistant",  "content": reply})
    state["history"] = state["history"][-20:]   # keep last 10 turns
    await msg.edit_text(reply[:4096])


# ── Text message router ───────────────────────────────────────────────────────

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Route all non-command text messages based on current user mode.
    Priority order:
      1. ❌ Cancel button (always handled first)
      2. Persistent keyboard buttons (📈 🔍 💬 ⚙️)
      3. Mode-specific input (chat, waiting_ticker, set_capital, set_risk)
      4. Direct ticker input (e.g. "HAL.NS")
      5. Fallback: AI chat
    """
    text  = update.message.text.strip()
    state = get_state(update.effective_user.id)
    mode  = state.get("mode", "idle")

    # ── 1. Cancel button ──────────────────────────────────────────────────────
    if text == "❌ Cancel":
        cancelled = cancel_active_task(update.effective_user.id)
        if cancelled:
            await update.message.reply_text("❌ Cancelled.", reply_markup=MAIN_KB)
        else:
            await update.message.reply_text("Nothing to cancel.", reply_markup=MAIN_KB)
        return

    # ── 2. Persistent keyboard buttons ───────────────────────────────────────
    if text == "📈 Analyse":
        state["mode"] = "waiting_ticker"
        await update.message.reply_text(
            "Which stock? Type the ticker symbol:\n"
            "e.g. <code>HAL</code> or <code>HAL.NS</code>",
            parse_mode=HTML,
        )
        return

    if text == "🔍 Scan Watchlist":
        await do_scan(update, ctx)
        return

    if text == "💬 Chat":
        await cmd_chat(update, ctx)
        return

    if text == "⚙️ Settings":
        await update.message.reply_text(
            "<b>Settings</b>\n\n"
            f"💰 Capital:            Rs.{cfg.RISK['capital']:,.0f}\n"
            f"📉 Risk per trade:     {cfg.RISK['risk_pct_per_trade']*100:.1f}%\n"
            f"📏 ATR SL multiplier:  {cfg.RISK['atr_sl_multiplier']}x\n\n"
            "<i>Use the buttons below to change capital or risk.</i>",
            parse_mode=HTML,
            reply_markup=SETTINGS_KB,
        )
        return

    # ── 3. Mode-specific input ────────────────────────────────────────────────

    if mode == "chat":
        # Forward message to AI and save to history
        msg   = await update.message.reply_text("💭 Thinking...")
        reply = chat(text, history=state.get("history", []), context=state.get("last_signal"))
        state["history"].append({"role": "user",      "content": text})
        state["history"].append({"role": "assistant",  "content": reply})
        state["history"] = state["history"][-20:]   # keep last 10 turns
        await msg.edit_text(reply[:4096])
        return

    if mode == "waiting_ticker":
        await do_analyse(update, ctx, text)
        return

    if mode == "set_capital":
        state["mode"] = "idle"
        try:
            amount = float(text.replace(",", "").replace("Rs.", "").strip())
            cfg.RISK["capital"] = amount
            await update.message.reply_text(f"✅ Capital set to Rs.{amount:,.0f}", reply_markup=MAIN_KB)
        except ValueError:
            await update.message.reply_text("Invalid. Enter a number like 500000.", reply_markup=MAIN_KB)
        return

    if mode == "set_risk":
        state["mode"] = "idle"
        try:
            pct = float(text.strip("%")) / 100
            if 0 < pct <= 0.1:
                cfg.RISK["risk_pct_per_trade"] = pct
                await update.message.reply_text(f"✅ Risk set to {pct*100:.1f}%", reply_markup=MAIN_KB)
            else:
                await update.message.reply_text("Must be 0.1%–10%.", reply_markup=MAIN_KB)
        except ValueError:
            await update.message.reply_text("Invalid. Enter a number like 1.5", reply_markup=MAIN_KB)
        return

    # ── 4. Direct ticker input ────────────────────────────────────────────────
    # Match: 2–20 alphanumeric chars with optional exchange suffix or crypto pair
    if (
        re.match(r"^[A-Za-z0-9&]{2,20}([.\-][A-Za-z0-9]{1,6})?$", text, re.IGNORECASE)
        and text.lower() not in _NOT_TICKERS
    ):
        await do_analyse(update, ctx, text)
        return

    # ── 5. Fallback: AI chat ──────────────────────────────────────────────────
    msg   = await update.message.reply_text("💭 Thinking...")
    reply = chat(text, history=state.get("history", []))
    state["history"].append({"role": "user",      "content": text})
    state["history"].append({"role": "assistant",  "content": reply})
    state["history"] = state["history"][-20:]   # keep last 10 turns
    await msg.edit_text(reply[:4096])


# ── Inline button callbacks ───────────────────────────────────────────────────

async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Handle all InlineKeyboardButton taps.
    Each button passes a callback_data string like "action:TICKER".
    """
    query = update.callback_query
    await query.answer()   # dismiss the loading spinner on the button
    data  = query.data
    state = get_state(update.effective_user.id)

    if data.startswith("explain:"):
        ticker = data.split(":", 1)[1]
        last   = state.get("last_signal", f"Signal for {ticker}")
        msg    = await query.message.reply_text("🤔 Thinking...")
        reply  = chat(
            "Explain this trading signal in plain language using ONLY the data in the context below. "
            "Focus on: (1) what the final VERDICT is (BUY/SELL/HOLD/NO TRADE) and why, "
            "(2) which case won — bull or bear — and the key evidence for it, "
            "(3) what the trader should specifically watch for to change this view. "
            "Do NOT describe it as bullish or bearish based on the 'Direction' field alone — "
            "the Direction is the raw technical vote, but the Verdict and Winner fields reflect "
            "the full six-perspective conclusion. Keep the explanation to 4–6 sentences.",
            context=last,
        )
        state["history"].append({"role": "assistant", "content": reply})
        state["history"] = state["history"][-20:]   # keep last 10 turns
        await msg.edit_text(reply[:4096])

    elif data.startswith("refresh:"):
        ticker = data.split(":", 1)[1]
        msg    = await query.message.reply_text(
            f"🔄 Refreshing <b>{escape(ticker)}</b>...", parse_mode=HTML
        )
        try:
            # Run synchronous pipeline in a thread — must not block the event loop
            text, result = await asyncio.to_thread(run_signal, ticker)
            state["last_signal"] = format_signal_plain(result)
            state["last_result"] = result
            await msg.edit_text(text, parse_mode=HTML, reply_markup=signal_inline_kb(result.ticker))
        except Exception as e:
            await msg.edit_text(f"❌ Error: {escape(str(e))}", parse_mode=HTML)

    elif data.startswith("alert:"):
        ticker = data.split(":", 1)[1]
        await query.message.reply_text(
            f"🔔 Alert noted for <b>{escape(ticker)}</b>.\n"
            f"<i>Price alerts will be available in a future update.</i>",
            parse_mode=HTML,
        )

    elif data.startswith("alltf:"):
        ticker  = data.split(":", 1)[1]
        result  = state.get("last_result")

        _tf_label = {"weekly": "📅 Weekly", "daily": "📆 Daily", "1hour": "⏱ 1 Hour", "15min": "⚡ 15 Min"}
        _dir_icon = {"BULLISH": "🟢 Looks Good", "BEARISH": "🔴 Looks Weak", "NEUTRAL": "🟡 Mixed"}
        _conf_map = {"HIGH": "Strong signal", "MEDIUM": "Moderate signal", "LOW": "Weak signal"}
        cur       = ticker_currency(ticker)

        lines = [f"<b>📊 {escape(ticker)} — All Timeframes</b>\n"]

        if result and result.timeframe_signals:
            for tf_key in ["weekly", "daily", "1hour", "15min"]:
                sig   = result.timeframe_signals.get(tf_key)
                label = _tf_label.get(tf_key, tf_key.title())
                if sig is None:
                    lines.append(f"{label}\n  <i>No data</i>\n")
                    continue
                view     = _dir_icon.get(sig.direction, sig.direction)
                conf_str = _conf_map.get(sig.confidence, sig.confidence)
                rr_str   = f"  |  R:R {sig.risk_reward:.1f}:1" if sig.risk_reward else ""
                entry_str = (
                    f"\n  Entry: {cur}{sig.entry_low:,.2f} – {cur}{sig.entry_high:,.2f}"
                    if sig.entry_low and sig.entry_high else ""
                )
                stop_str  = f"  |  Stop: {cur}{sig.stop_loss:,.2f}" if sig.stop_loss else ""
                lines.append(f"{label}\n  {view}  —  {conf_str}{rr_str}{entry_str}{stop_str}\n")
        else:
            lines.append("<i>No timeframe data available. Run /analyse first.</i>")

        await query.message.reply_text("\n".join(lines), parse_mode=HTML)

    elif data == "set:capital":
        state["mode"] = "set_capital"
        await query.message.reply_text(
            "Enter new capital in Rs. (e.g. <code>500000</code>):", parse_mode=HTML
        )

    elif data == "set:risk":
        state["mode"] = "set_risk"
        await query.message.reply_text(
            "Enter risk per trade as % (e.g. <code>1.5</code>):", parse_mode=HTML
        )

    elif data == "set:watchlist":
        lines = ["<b>Current Watchlist</b>\n"]
        for name, ticker in cfg.WATCHLIST.items():
            lines.append(f"  • {escape(name)} — <code>{escape(ticker)}</code>")
        await query.message.reply_text("\n".join(lines), parse_mode=HTML)


# ── Entry point ───────────────────────────────────────────────────────────────

async def _post_init(app: Application) -> None:
    """
    Runs once after the bot starts up.
    Registers the command list with Telegram so the "/" menu shows all commands.
    """
    commands = [
        BotCommand("start",       "Welcome & quick start"),
        BotCommand("analyse",     "Signal for a stock — /analyse HAL"),
        BotCommand("scan",        "Scan full watchlist for signals"),
        BotCommand("explain",     "Explain the last signal in plain English"),
        BotCommand("chat",        "Ask the AI anything about markets"),
        BotCommand("done",        "Exit chat mode"),
        BotCommand("watchlist",   "View the scan watchlist"),
        BotCommand("add",         "Add ticker to watchlist — /add AAPL"),
        BotCommand("remove",      "Remove ticker from watchlist — /remove AAPL"),
        BotCommand("setcapital",  "Set trading capital — /setcapital 500000"),
        BotCommand("setrisk",     "Set risk per trade % — /setrisk 1.5"),
        BotCommand("cancel",      "Cancel any running operation"),
        BotCommand("help",        "Full command reference"),
    ]
    await app.bot.set_my_commands(commands)
    log.info("Bot commands registered with Telegram.")


def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        print("ERROR: BOT_TOKEN not set in .env")
        sys.exit(1)

    print(f"AI provider: {provider_label()}")
    if get_provider() == "none":
        print("WARNING: No AI API key found. Add GROQ_API_KEY or GEMINI_API_KEY to .env")

    app = (
        Application.builder()
        .token(token)
        .post_init(_post_init)   # registers slash commands with Telegram on startup
        .build()
    )

    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("help",        cmd_help))
    app.add_handler(CommandHandler("analyse",     cmd_analyse))
    app.add_handler(CommandHandler("scan",        cmd_scan))
    app.add_handler(CommandHandler("explain",     cmd_explain))
    app.add_handler(CommandHandler("chat",        cmd_chat))
    app.add_handler(CommandHandler("done",        cmd_done))
    app.add_handler(CommandHandler("watchlist",   cmd_watchlist))
    app.add_handler(CommandHandler("add",         cmd_add))
    app.add_handler(CommandHandler("remove",      cmd_remove))
    app.add_handler(CommandHandler("setcapital",  cmd_setcapital))
    app.add_handler(CommandHandler("setrisk",     cmd_setrisk))
    app.add_handler(CommandHandler("cancel",      cmd_cancel))

    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    print("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
