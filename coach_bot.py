import os
import json
import logging
from datetime import datetime, time
from pathlib import Path

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)
import google.generativeai as genai

# ── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
DATA_FILE      = "user_data.json"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    system_instruction="""You are a tough-love personal coach for a 26-year-old Pakistani developer living in Qatar.

His goals:
- Career: Go from 18k to 35-50k QAR salary in 12 months via DevOps/AWS skills
- Body: Build strength, run a marathon, develop physical discipline
- Communication: Stop rambling, speak with clarity, confidence, and impact
- Finance: Invest in PSX stocks and Pakistan RDA, target 15-50% annual returns
- Business: Build an AI services company earning 10k-100k/month with his friend

Your coaching style:
- Direct, honest, no sugarcoating
- Short replies — max 3-4 sentences unless teaching something specific
- When practicing communication: give a scenario, evaluate his response, suggest ONE specific upgrade
- When he skips tasks: acknowledge briefly, redirect to action immediately
- For career questions: give concrete technical advice, not general motivation
- For investing: focus on PSX, RDA, and ETFs only
- If he writes unclearly: point it out kindly as communication practice

His weekly schedule:
Mon/Wed/Fri = AWS study + Weights + Communication practice
Tue/Thu = Project build + Running + Money/Business action
Sat = Long run + Portfolio + Deep study
Sun = Rest + 30 min weekly review only"""
)

# ── Weekly routine ─────────────────────────────────────────────────────────────
WEEKLY_TASKS = {
    0: [  # Monday
        {"id": "aws",  "text": "AWS study — 45 min (IAM, EC2, S3 — pick up where you left off)"},
        {"id": "gym",  "text": "Gym — Squats, Bench Press, OHP (log weights in Strong app)"},
        {"id": "comm", "text": "Record yourself talking 5 min on any topic. Watch it back."},
    ],
    1: [  # Tuesday
        {"id": "build",  "text": "Portfolio project — add 1 feature or fix today"},
        {"id": "run",    "text": "Run 3km — slow enough to hold a conversation (Zone 2)"},
        {"id": "money",  "text": "Read 1 article on PSX stocks or RDA returns (Topline Securities)"},
    ],
    2: [  # Wednesday
        {"id": "aws",  "text": "AWS study — 45 min + answer 5 practice exam questions"},
        {"id": "gym",  "text": "Gym — Deadlifts, Rows, Bicep curls"},
        {"id": "comm", "text": "Read 20 pages of your communication book"},
    ],
    3: [  # Thursday
        {"id": "build",  "text": "Portfolio project — connect one more API or UI component"},
        {"id": "run",    "text": "Run 3km + 10 min stretching after"},
        {"id": "biz",    "text": "1 business action — message 1 potential client or research a niche"},
    ],
    4: [  # Friday
        {"id": "aws",  "text": "AWS study — 45 min, focus on your weakest topic this week"},
        {"id": "gym",  "text": "Gym — Squats, Bench, OHP (try to beat Monday's weights)"},
        {"id": "comm", "text": "Record yourself again — compare to Monday's recording"},
    ],
    5: [  # Saturday
        {"id": "run",   "text": "Long run — 5km+ at easy pace. This builds your marathon base."},
        {"id": "build", "text": "Portfolio — polish GitHub README, push commits, update LinkedIn"},
        {"id": "deep",  "text": "Deep study — 1 hour on investing strategy or business planning"},
    ],
    6: [  # Sunday
        {"id": "rest",   "text": "Full rest. No new goals today. Recover."},
        {"id": "review", "text": "30-min weekly review only — what did you do, skip, and ONE adjustment"},
    ],
}

DAILY_KNOWLEDGE = {
    0: "☁️ *AWS tip:* IAM roles > access keys. Always attach roles to EC2 — they rotate automatically. Access keys don't. Senior devs know this.",
    1: "💬 *Comm tip:* Lead with your conclusion, then explain. Don't make people wait to hear your point. BLUF — Bottom Line Up Front.",
    2: "📈 *PSX tip:* Follow Topline Securities research. Focus on fertilizer (ENGRO, FFC) and banking (HBL, UBL) sectors for stability.",
    3: "🏗 *Career tip:* System design = biggest salary jump. Study: load balancers, caching, and database sharding this month.",
    4: "🎙 *Speaking tip:* After your key point — pause 2 full seconds. Feels awkward to you. Sounds powerful to them.",
    5: "💰 *Money tip:* Pakistan RDA gives 20-22% on PKR certificates. Open via HBL or Meezan digitally from Qatar. Best safe return available to you.",
    6: "🔁 *Sunday rule:* Plan only today. 30 min max. What did I do, what did I skip, what is ONE adjustment. Then close the notebook.",
}

# ── Data helpers ───────────────────────────────────────────────────────────────
def load_data() -> dict:
    if Path(DATA_FILE).exists():
        with open(DATA_FILE) as f:
            return json.load(f)
    return {}

def save_data(data: dict):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_user(data: dict, uid: str) -> dict:
    if uid not in data:
        data[uid] = {
            "streak": 0,
            "last_done_date": None,
            "tasks_done_today": [],
            "history": [],
            "conversation": [],
        }
    return data[uid]

# ── Gemini chat ────────────────────────────────────────────────────────────────
async def ask_gemini(user: dict, message: str) -> str:
    try:
        history = user.get("conversation", [])
        chat = gemini_model.start_chat(history=history)
        response = chat.send_message(message)
        user["conversation"] = [
            {"role": m.role, "parts": [p.text for p in m.parts]}
            for m in chat.history
        ]
        if len(user["conversation"]) > 20:
            user["conversation"] = user["conversation"][-20:]
        return response.text
    except Exception as e:
        log.error(f"Gemini error: {e}")
        return "Connection issue — try again in a moment."

# ── Task helpers ───────────────────────────────────────────────────────────────
def get_today_tasks() -> list:
    return WEEKLY_TASKS.get(datetime.now().weekday(), [])

def format_tasks(tasks: list, done_ids: list) -> str:
    lines = []
    for i, t in enumerate(tasks, 1):
        tick = "✅" if t["id"] in done_ids else f"{i}."
        lines.append(f"{tick} {t['text']}")
    return "\n".join(lines)

def try_complete_streak(user: dict) -> bool:
    today = datetime.now().date().isoformat()
    tasks = get_today_tasks()
    all_ids = [t["id"] for t in tasks]
    done = user.get("tasks_done_today", [])
    if all(tid in done for tid in all_ids):
        if user.get("last_done_date") != today:
            user["streak"] = user.get("streak", 0) + 1
            user["last_done_date"] = today
            return True
    return False

# ── Handlers ───────────────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    uid = str(update.effective_user.id)
    get_user(data, uid)
    save_data(data)
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("✅ My Tasks"), KeyboardButton("🔥 My Streak")],
         [KeyboardButton("🎙 Practice Communication"), KeyboardButton("🧠 Today's Knowledge")],
         [KeyboardButton("📊 Weekly Review")]],
        resize_keyboard=True
    )
    await update.message.reply_text(
        "👋 *Life Coach Bot activated.*\n\n"
        "I send your 3 daily missions at 5:30am Qatar time, track your streaks, "
        "and coach you on communication anytime.\n\n"
        "Use the buttons or just talk to me.",
        parse_mode="Markdown", reply_markup=kb
    )

async def tasks_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    uid = str(update.effective_user.id)
    user = get_user(data, uid)
    tasks = get_today_tasks()
    done = user.get("tasks_done_today", [])
    done_count = sum(1 for t in tasks if t["id"] in done)
    save_data(data)
    await update.message.reply_text(
        f"📋 *{datetime.now().strftime('%A')} — {done_count}/{len(tasks)} done*\n\n"
        f"{format_tasks(tasks, done)}\n\n"
        f"Reply `DONE aws`, `DONE gym`, `DONE run`, `DONE comm`, `DONE build`, `DONE money`",
        parse_mode="Markdown"
    )

async def streak_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    uid = str(update.effective_user.id)
    user = get_user(data, uid)
    streak = user.get("streak", 0)
    save_data(data)
    if streak == 0:
        msg = "🔥 Streak: *0 days*\n\nComplete all tasks today to start one. The streak becomes the system."
    elif streak < 7:
        msg = f"🔥 Streak: *{streak} days*\n\nGood start. 7 days is where it becomes automatic."
    elif streak < 30:
        msg = f"🔥 Streak: *{streak} days*\n\nSolid. You're building a real identity now."
    else:
        msg = f"🔥 Streak: *{streak} days*\n\nThis is who you are now. Elite."
    await update.message.reply_text(msg, parse_mode="Markdown")

async def knowledge_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tip = DAILY_KNOWLEDGE.get(datetime.now().weekday(), "Keep showing up. That's 80% of the game.")
    await update.message.reply_text(f"🧠 *Today's Knowledge Drop*\n\n{tip}", parse_mode="Markdown")

async def practice_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    uid = str(update.effective_user.id)
    user = get_user(data, uid)
    reply = await ask_gemini(user,
        "Start a communication practice session. Give me one realistic scenario "
        "I'd face at work or socially in Qatar. Ask me to respond naturally.")
    save_data(data)
    await update.message.reply_text(f"🎙 *Comm Practice*\n\n{reply}", parse_mode="Markdown")

async def review_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    uid = str(update.effective_user.id)
    user = get_user(data, uid)
    streak = user.get("streak", 0)
    save_data(data)
    await update.message.reply_text(
        f"📊 *Weekly Review*\n\n🔥 Streak: {streak} days\n\n"
        f"Answer these 3 questions:\n"
        f"1. What did you complete this week?\n"
        f"2. What did you skip and why?\n"
        f"3. ONE adjustment for next week?\n\n"
        f"Reply here — I'll give you honest feedback.",
        parse_mode="Markdown"
    )

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    uid = str(update.effective_user.id)
    user = get_user(data, uid)
    text = update.message.text.strip()
    tl = text.lower()

    if "my tasks" in tl:      save_data(data); return await tasks_cmd(update, ctx)
    if "my streak" in tl:     save_data(data); return await streak_cmd(update, ctx)
    if "practice" in tl:      save_data(data); return await practice_cmd(update, ctx)
    if "knowledge" in tl:     save_data(data); return await knowledge_cmd(update, ctx)
    if "weekly review" in tl: save_data(data); return await review_cmd(update, ctx)

    if tl.startswith("done"):
        keyword = tl.replace("done", "").strip()
        tasks = get_today_tasks()
        matched = next(
            (t for t in tasks if keyword in t["id"].lower() or keyword in t["text"].lower() or keyword == ""),
            None
        )
        if matched:
            done_list = user.setdefault("tasks_done_today", [])
            if matched["id"] not in done_list:
                done_list.append(matched["id"])
                user.setdefault("history", []).append({
                    "date": datetime.now().date().isoformat(),
                    "task": matched["id"],
                })
            all_tasks = get_today_tasks()
            done_count = sum(1 for t in all_tasks if t["id"] in done_list)
            remaining = len(all_tasks) - done_count
            streak_hit = try_complete_streak(user)
            save_data(data)
            if streak_hit:
                return await update.message.reply_text(
                    f"🔥 *ALL DONE! Streak: {user['streak']} days*\n\n"
                    f"That's who you are. Tomorrow, same time.\n\n"
                    f"{DAILY_KNOWLEDGE.get(datetime.now().weekday(), '')}",
                    parse_mode="Markdown"
                )
            elif remaining == 0:
                return await update.message.reply_text(f"✅ *{matched['id'].upper()}* logged. All tasks done 💪", parse_mode="Markdown")
            else:
                return await update.message.reply_text(
                    f"✅ *{matched['id'].upper()}* logged — {done_count}/{len(all_tasks)} done\n\n{format_tasks(all_tasks, done_list)}",
                    parse_mode="Markdown"
                )
        else:
            save_data(data)
            return await update.message.reply_text(
                "Which task? Try: `DONE aws` / `DONE gym` / `DONE run` / `DONE comm` / `DONE build` / `DONE money`",
                parse_mode="Markdown"
            )

    reply = await ask_gemini(user, text)
    save_data(data)
    await update.message.reply_text(reply)

# ── Scheduled jobs ─────────────────────────────────────────────────────────────
async def morning_briefing(ctx: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    tasks = get_today_tasks()
    knowledge = DAILY_KNOWLEDGE.get(datetime.now().weekday(), "")
    for uid, user in data.items():
        user["tasks_done_today"] = []
        try:
            await ctx.bot.send_message(
                chat_id=int(uid),
                text=f"🌅 *Good morning! {datetime.now().strftime('%A')} missions:*\n\n"
                     f"{format_tasks(tasks, [])}\n\n🧠 {knowledge}\n\n"
                     f"Reply *DONE [task]* as you finish each one.",
                parse_mode="Markdown"
            )
        except Exception as e:
            log.warning(f"Could not message {uid}: {e}")
    save_data(data)

async def evening_checkin(ctx: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    tasks = get_today_tasks()
    for uid, user in data.items():
        done = user.get("tasks_done_today", [])
        remaining = [t for t in tasks if t["id"] not in done]
        if not remaining:
            continue
        try:
            await ctx.bot.send_message(
                chat_id=int(uid),
                text=f"⚡ *Still open:*\n\n" + "\n".join(f"• {t['text'][:60]}" for t in remaining) +
                     "\n\nYou have 2 hours. Make it count.",
                parse_mode="Markdown"
            )
        except Exception as e:
            log.warning(f"Could not message {uid}: {e}")

async def night_summary(ctx: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    tasks = get_today_tasks()
    for uid, user in data.items():
        done = user.get("tasks_done_today", [])
        done_count = sum(1 for t in tasks if t["id"] in done)
        streak = user.get("streak", 0)
        if done_count == len(tasks):
            msg = f"🌙 *Day complete.* Streak: {streak} days 🔥\n\nSleep well. Tomorrow 5:30am."
        elif done_count > 0:
            msg = f"🌙 *{done_count}/{len(tasks)} today.* Streak: {streak}\n\nPartial counts. Go full tomorrow."
        else:
            msg = f"🌙 *Zero today.* Streak: {streak}\n\nDon't justify it. Tomorrow 5:30am. That's all."
        try:
            await ctx.bot.send_message(chat_id=int(uid), text=msg, parse_mode="Markdown")
        except Exception as e:
            log.warning(f"Could not message {uid}: {e}")

# ── Entry point ────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tasks", tasks_cmd))
    app.add_handler(CommandHandler("streak", streak_cmd))
    app.add_handler(CommandHandler("knowledge", knowledge_cmd))
    app.add_handler(CommandHandler("practice", practice_cmd))
    app.add_handler(CommandHandler("review", review_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    jq = app.job_queue
    jq.run_daily(morning_briefing, time=time(2, 30))   # 5:30am Qatar (UTC+3)
    jq.run_daily(evening_checkin,  time=time(17, 0))   # 8:00pm Qatar
    jq.run_daily(night_summary,    time=time(18, 30))  # 9:30pm Qatar

    log.info("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
