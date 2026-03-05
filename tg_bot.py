#!/usr/bin/env python3
"""Telegram Fitness Bot — персональный помощник для тренировок."""
import os, json, logging, warnings, uuid
from datetime import datetime, time as dtime
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes, filters,
)

# ─── Config ───────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.getenv("BOT_TOKEN", "")
DEVELOPER_ID = int(os.getenv("DEVELOPER_ID", "0"))
DATA_FILE   = Path("data.json")
Path("logs").mkdir(exist_ok=True)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(),
              logging.FileHandler("logs/bot.log", encoding="utf-8")],
)
logger = logging.getLogger(__name__)

# ─── States ───────────────────────────────────────────────────────────────────
(
    MAIN_MENU,              # 0
    CREATE_NAME,            # 1
    CREATE_PHASES,          # 2
    CREATE_PHASE_SEL,       # 3  кнопки фаз
    CREATE_PHASE_DAYS,      # 4  выбор дней для фазы
    CREATE_PHASE_TIME,      # 5  время для фазы
    CREATE_MUSCLE_SEL,      # 6  кнопки дней → ввод мышц/упражнений
    CREATE_MUSCLE_ENTER,    # 7  ввод группы мышц
    CREATE_EXERCISE_ENTER,  # 8  ввод упражнений
    SW_SELECT,              # 9
    SW_PHASE,               # 10
    SW_DAY,                 # 11
    EW_SELECT,              # 12
    EDIT_MENU,              # 13
    EDIT_NAME,              # 14
    EDIT_PHASE_SEL,         # 15
    EDIT_PHASE_MENU,        # 16
    EDIT_PHASE_DAYS,        # 17
    EDIT_PHASE_TIME,        # 18
    EDIT_MUSCLE_SEL,        # 19  кнопки дней для редактирования
    EDIT_DAY_OPTS,          # 20  выбор что редактировать (мышцы/упражнения)
    EDIT_MUSCLE_ENTER,      # 21
    EDIT_EXERCISE_ENTER,    # 22
) = range(23)

# ─── Days ─────────────────────────────────────────────────────────────────────
DAYS_ORDER = ["mon","tue","wed","thu","fri","sat","sun"]
DAY_NAMES  = {"mon":"Понедельник","tue":"Вторник","wed":"Среда",
               "thu":"Четверг","fri":"Пятница","sat":"Суббота","sun":"Воскресенье"}
DAY_SHORT  = {"mon":"Пн","tue":"Вт","wed":"Ср","thu":"Чт","fri":"Пт","sat":"Сб","sun":"Вс"}
DAY_WEEKDAY= {"mon":0,"tue":1,"wed":2,"thu":3,"fri":4,"sat":5,"sun":6}

# ─── Data layer ───────────────────────────────────────────────────────────────
def load_data() -> dict:
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE,"r",encoding="utf-8") as f: return json.load(f)
        except Exception: return {}
    return {}

def save_data(data:dict):
    with open(DATA_FILE,"w",encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user_workouts(uid:int) -> list:
    return load_data().get(str(uid),{}).get("workouts",[])

def upsert_workout(uid:int, workout:dict):
    data = load_data()
    key = str(uid)
    if key not in data: data[key] = {"workouts":[]}
    ws = data[key]["workouts"]
    for i,w in enumerate(ws):
        if w["id"] == workout["id"]:
            ws[i] = workout; save_data(data); return
    ws.append(workout); save_data(data)

def remove_workout(uid:int, wid:str):
    data = load_data(); key = str(uid)
    if key in data:
        data[key]["workouts"] = [w for w in data[key]["workouts"] if w["id"]!=wid]
        save_data(data)

# ─── Notifications ────────────────────────────────────────────────────────────
async def send_notification(context: ContextTypes.DEFAULT_TYPE):
    d = context.job.data
    await context.bot.send_message(
        chat_id=d["user_id"],
        text=f"⏰ *Напоминание!*\n\nЧерез час тренировка *{d['name']}* в {d['time']} 💪",
        parse_mode="Markdown",
    )

def schedule_notifications(app:Application, uid:int, workout:dict):
    # Проверка что job_queue доступен
    if not app or not app.job_queue:
        logger.warning("job_queue not available, notifications will not be scheduled")
        return
    
    wid = workout["id"]
    for job in list(app.job_queue.jobs()):
        if job.name and job.name.startswith(f"notif_{uid}_{wid}"):
            job.schedule_removal()
    for pk, phase in workout.get("phases_data",{}).items():
        ts = phase.get("time",""); days = phase.get("days",[])
        if not ts or not days: continue
        try:
            h,m = map(int,ts.split(":")); nt = dtime((h-1)%24, m)
        except Exception: continue
        ptb = tuple(DAY_WEEKDAY[d] for d in days if d in DAY_WEEKDAY)
        num = pk.replace("phase_","")
        app.job_queue.run_daily(
            send_notification, time=nt, days=ptb,
            name=f"notif_{uid}_{wid}_{pk}",
            data={"user_id":uid, "name":f"{workout['name']} (Фаза {num})", "time":ts},
        )

# ─── Keyboards ────────────────────────────────────────────────────────────────
def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏋️ Начать тренировку",        callback_data="menu:start")],
        [InlineKeyboardButton("✏️ Редактировать тренировки", callback_data="menu:edit")],
        [InlineKeyboardButton("➕ Создать тренировку",        callback_data="menu:create")],
    ])

def cancel_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="menu:main")]])

def back_menu_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="menu:main")]])

def days_multi_kb(selected:list):
    rows,row = [],[]
    for i,d in enumerate(DAYS_ORDER):
        mark = "✅" if d in selected else "☐"
        row.append(InlineKeyboardButton(f"{mark} {DAY_NAMES[d]}", callback_data=f"day:{d}"))
        if len(row)==2: rows.append(row); row=[]
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("✔️ Подтвердить", callback_data="day:confirm")])
    rows.append([InlineKeyboardButton("❌ Отмена",       callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)

def workouts_kb(workouts:list, prefix:str):
    rows = [[InlineKeyboardButton(f"🏋️ {w['name']}", callback_data=f"{prefix}:{w['id']}")] for w in workouts]
    rows.append([InlineKeyboardButton("◀️ Назад", callback_data=f"{prefix}:back")])
    rows.append([InlineKeyboardButton("🏠 Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)

def phase_select_kb(n:int, prefix:str, wid:str, done:list=None):
    done = done or []
    rows = []
    for i in range(n):
        pk = f"phase_{i+1}"; mark = "✅ " if pk in done else ""
        rows.append([InlineKeyboardButton(f"{mark}Фаза {i+1}", callback_data=f"{prefix}:{wid}:{pk}")])
    rows.append([InlineKeyboardButton("◀️ К тренировкам", callback_data=f"{prefix}:back")])
    rows.append([InlineKeyboardButton("🏠 Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)

def create_phase_sel_kb(n:int, phases_config:dict):
    """Кнопки фаз. Сохранить — если хотя бы одна фаза настроена."""
    rows = []
    for i in range(n):
        pk = f"phase_{i+1}"
        done = bool(phases_config.get(pk,{}).get("days"))
        mark = "✅ " if done else ""
        rows.append([InlineKeyboardButton(f"{mark}Фаза {i+1}", callback_data=f"cph:{pk}")])
    # Кнопка сохранить появляется если хотя бы 1 фаза готова
    any_done = any(phases_config.get(f"phase_{i+1}",{}).get("days") for i in range(n))
    if any_done:
        rows.append([InlineKeyboardButton("💾 Сохранить тренировку", callback_data="cph:save")])
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)

def muscle_day_kb(days:list, muscles:dict, exercises:dict):
    """Кнопки дней с индикатором заполнения: ✅ мышцы+упражнения | 📋 только мышцы | ☐ пусто."""
    rows = []
    for d in days:
        has_m = bool(muscles.get(d))
        has_e = bool(exercises.get(d))
        if has_m and has_e:   icon = "✅"
        elif has_m:            icon = "📋"
        else:                  icon = "☐"
        label = f"{icon} {DAY_NAMES[d]}"
        if muscles.get(d): label += f": {muscles[d]}"
        rows.append([InlineKeyboardButton(label, callback_data=f"mday:{d}")])
    rows.append([InlineKeyboardButton("💾 Сохранить фазу", callback_data="mday:save")])
    rows.append([InlineKeyboardButton("◀️ Назад",          callback_data="mday:back")])
    rows.append([InlineKeyboardButton("🏠 Главное меню",   callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)

def workout_days_kb(days:list, prefix:str, wid:str, phase:str, muscles:dict=None):
    muscles = muscles or {}
    rows = []
    for d in days:
        if d not in DAY_NAMES: continue
        label = DAY_NAMES[d]
        m = muscles.get(d, "")
        if m:
            m_short = m[:22] + "…" if len(m) > 22 else m
            label += f"  ·  {m_short}"
        rows.append([InlineKeyboardButton(label, callback_data=f"{prefix}:{wid}:{phase}:{d}")])
    rows.append([InlineKeyboardButton("◀️ К фазам", callback_data=f"{prefix}:back:{wid}")])
    rows.append([InlineKeyboardButton("🏠 Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)

# ─── Helpers ──────────────────────────────────────────────────────────────────
async def send_or_edit(update:Update, text:str, kb:InlineKeyboardMarkup, pm="Markdown"):
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=pm, reply_markup=kb)
    else:
        await update.message.reply_text(text, parse_mode=pm, reply_markup=kb)

def phase_summary(workout:dict) -> str:
    lines = []
    for i in range(workout["phases"]):
        pk = f"phase_{i+1}"
        phase = workout["phases_data"].get(pk, {})
        days_str = ", ".join(DAY_SHORT.get(d,d) for d in phase.get("days",[]))
        t = phase.get("time","—")
        lines.append(f"*Фаза {i+1}:* {days_str} в {t}")
    return "\n".join(lines)

# ─── Validation ───────────────────────────────────────────────────────────────
def get_keyboard_for_state(state: int, context: ContextTypes.DEFAULT_TYPE):
    """Возвращает клавиатуру для указанного состояния."""
    c = context.user_data.get("c", {})
    w = context.user_data.get("editing")
    
    if state == MAIN_MENU:
        return main_menu_kb()
    
    elif state == CREATE_PHASE_SEL:
        return create_phase_sel_kb(c.get("phases", 1), c.get("phases_config", {}))
    
    elif state == CREATE_PHASE_DAYS:
        return days_multi_kb(c.get("tmp_days", []))
    
    elif state == CREATE_MUSCLE_SEL:
        pk = c.get("editing_phase", "phase_1")
        phase = c.get("phases_config", {}).get(pk, {})
        return muscle_day_kb(phase.get("days", []), 
                            c.get("tmp_muscles", {}), 
                            c.get("tmp_exercises", {}))
    
    elif state == SW_SELECT:
        ws = get_user_workouts(context._user_id) if hasattr(context, "_user_id") else []
        return workouts_kb(ws, "sw")
    
    elif state == SW_PHASE:
        active_w = context.user_data.get("active")
        if active_w:
            done = [pk for pk, pv in active_w.get("phases_data", {}).items() if pv.get("days")]
            return phase_select_kb(active_w["phases"], "sp", active_w["id"], done)
        return main_menu_kb()
    
    elif state == SW_DAY:
        active_w = context.user_data.get("active")
        pk = context.user_data.get("active_phase", "phase_1")
        if active_w:
            phase = active_w["phases_data"].get(pk, {})
            return workout_days_kb(phase.get("days", []), "sd", active_w["id"], pk, phase.get("muscles", {}))
        return main_menu_kb()
    
    elif state == EW_SELECT:
        ws = get_user_workouts(context._user_id) if hasattr(context, "_user_id") else []
        return workouts_kb(ws, "ew")
    
    elif state == EDIT_MENU:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Переименовать",         callback_data="em:rename")],
            [InlineKeyboardButton("⚙️ Редактировать фазу",    callback_data="em:phases")],
            [InlineKeyboardButton("🗑 Удалить тренировку",    callback_data="em:delete")],
            [InlineKeyboardButton("🏠 Главное меню",          callback_data="menu:main")],
        ])
    
    elif state == EDIT_PHASE_SEL:
        if w:
            done = [pk for pk, pv in w.get("phases_data", {}).items() if pv.get("days")]
            return phase_select_kb(w["phases"], "eph", w["id"], done)
        return main_menu_kb()
    
    elif state == EDIT_PHASE_MENU:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 Изменить дни",          callback_data="epm:days")],
            [InlineKeyboardButton("⏰ Изменить время",         callback_data="epm:time")],
            [InlineKeyboardButton("💪 Редактировать дни/мышцы/упражнения", callback_data="epm:muscles")],
            [InlineKeyboardButton("◀️ К фазам",               callback_data="epm:back")],
            [InlineKeyboardButton("🏠 Главное меню",          callback_data="menu:main")],
        ])
    
    elif state == EDIT_PHASE_DAYS:
        sel = context.user_data.get("edit_tmp_days", [])
        return days_multi_kb(sel)
    
    elif state == EDIT_MUSCLE_SEL:
        if w:
            pk = context.user_data.get("edit_pk", "phase_1")
            phase = w["phases_data"].get(pk, {})
            muscles = context.user_data.get("edit_tmp_muscles", {})
            exercises = context.user_data.get("edit_tmp_exercises", {})
            return muscle_day_kb(phase.get("days", []), muscles, exercises)
        return main_menu_kb()
    
    elif state == EDIT_DAY_OPTS:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("💪 Изменить группу мышц",  callback_data="edopt:muscles")],
            [InlineKeyboardButton("📝 Изменить упражнения",   callback_data="edopt:exercises")],
            [InlineKeyboardButton("◀️ Назад к дням",          callback_data="edopt:back")],
        ])
    
    return cancel_kb()

async def button_only_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик для состояний где требуются только кнопки."""
    if not update.message:
        return ConversationHandler.END
    
    # Определяем текущее состояние
    current_state = MAIN_MENU
    for state_name in ["_conv_state", "state"]:
        if state_name in context.user_data:
            current_state = context.user_data[state_name]
            break
    
    # Сохраняем user_id для использования в get_keyboard_for_state
    context._user_id = update.effective_user.id
    
    keyboard = get_keyboard_for_state(current_state, context)
    
    await update.message.reply_text(
        "⚠️ *Ошибка ввода!*\n\n"
        "В данном меню нужно использовать *кнопки* ниже.\n"
        "Ввод текста не поддерживается.\n\n"
        "👇 Пожалуйста, выбери один из вариантов:",
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    
    return current_state

# ─── /start ───────────────────────────────────────────────────────────────────
async def cmd_start(update:Update, context:ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    u = update.effective_user
    text = (
        f"👋 Привет, *{u.first_name}*!\n\n"
        "Я твой персональный *фитнес-бот* 💪\n\n"
        "━━━━━━━━━━━━━━━━━\n"
        "🏋️ *Начать тренировку* — открой программу и приступай\n"
        "✏️ *Редактировать* — изменяй дни, время, упражнения\n"
        "➕ *Создать* — построй свою программу с нуля\n"
        "⏰ *Напоминания* — уведомления за 1 час до тренировки\n"
        "━━━━━━━━━━━━━━━━━\n\n"
        "Выбери действие:"
    )
    await send_or_edit(update, text, main_menu_kb())
    return MAIN_MENU

# ─── Main menu ────────────────────────────────────────────────────────────────
async def main_menu_handler(update:Update, context:ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    action = q.data.split(":")[1]

    if action == "main": return await cmd_start(update, context)

    if action == "start":
        ws = get_user_workouts(update.effective_user.id)
        if not ws:
            await q.edit_message_text("📭 Пока нет тренировок. Создай первую!", parse_mode="Markdown", reply_markup=back_menu_kb())
            return MAIN_MENU
        await q.edit_message_text("🏋️ *Выбери тренировку:*", parse_mode="Markdown", reply_markup=workouts_kb(ws,"sw"))
        return SW_SELECT

    if action == "edit":
        ws = get_user_workouts(update.effective_user.id)
        if not ws:
            await q.edit_message_text("📭 Нет тренировок. Создай первую!", parse_mode="Markdown", reply_markup=back_menu_kb())
            return MAIN_MENU
        await q.edit_message_text("✏️ *Выбери тренировку:*", parse_mode="Markdown", reply_markup=workouts_kb(ws,"ew"))
        return EW_SELECT

    if action == "create":
        context.user_data["c"] = {}
        await q.edit_message_text(
            "➕ *Создание тренировки*\n\nШаг 1 — Введи *название* тренировки:",
            parse_mode="Markdown", reply_markup=cancel_kb(),
        )
        return CREATE_NAME

    return MAIN_MENU

# ═══════════════════════ CREATE FLOW ══════════════════════════════════════════

async def create_name(update:Update, context:ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Название не может быть пустым:"); return CREATE_NAME
    context.user_data["c"]["name"] = name
    await update.message.reply_text(
        f"✅ Название: *{name}*\n\nШаг 2 — Сколько *фаз* в тренировке? (1–6)\n"
        "_(фаза = период с набором упражнений, например 4–6 недель)_",
        parse_mode="Markdown", reply_markup=cancel_kb(),
    )
    return CREATE_PHASES

async def create_phases(update:Update, context:ContextTypes.DEFAULT_TYPE) -> int:
    try:
        n = int(update.message.text.strip())
        if not (1 <= n <= 6): raise ValueError
    except ValueError:
        await update.message.reply_text("Введи число от 1 до 6:"); return CREATE_PHASES
    c = context.user_data["c"]
    c["phases"] = n; c["phases_config"] = {}; c["wid"] = str(uuid.uuid4())[:8]
    await update.message.reply_text(
        f"✅ Фаз: *{n}*\n\nТеперь настрой каждую фазу.\n"
        "Выбери фазу → укажи дни и время → запиши группы мышц и упражнения:\n\n"
        "💡 *Сохранить* можно когда настроена хотя бы 1 фаза",
        parse_mode="Markdown",
        reply_markup=create_phase_sel_kb(n, {}),
    )
    return CREATE_PHASE_SEL

async def create_phase_sel(update:Update, context:ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    if q.data == "menu:main": return await cmd_start(update, context)
    c = context.user_data["c"]
    token = q.data.split(":")[1]

    if token == "save": return await finalize_create(update, context)

    pk = token
    c["editing_phase"] = pk
    existing = c["phases_config"].get(pk, {})
    c["tmp_days"] = list(existing.get("days", []))

    num = pk.replace("phase_","")
    await q.edit_message_text(
        f"📅 *Фаза {num} — Шаг 1: Выбери дни тренировок*\n\nНажимай дни, затем подтверди:",
        parse_mode="Markdown", reply_markup=days_multi_kb(c["tmp_days"]),
    )
    return CREATE_PHASE_DAYS

async def create_phase_days(update:Update, context:ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    if q.data == "menu:main": return await cmd_start(update, context)
    c = context.user_data["c"]; token = q.data.split(":")[1]

    if token == "confirm":
        if not c.get("tmp_days"):
            await q.answer("Выбери хотя бы один день!", show_alert=True); return CREATE_PHASE_DAYS
        ds = ", ".join(DAY_NAMES[d] for d in c["tmp_days"])
        num = c["editing_phase"].replace("phase_","")
        await q.edit_message_text(
            f"✅ Дни фазы {num}: *{ds}*\n\n*Шаг 2:* В какое время начинаются тренировки?\n"
            "Введи в формате *ЧЧ:ММ* (например `09:00`):",
            parse_mode="Markdown", reply_markup=cancel_kb(),
        )
        return CREATE_PHASE_TIME

    if token in DAYS_ORDER:
        sel = c["tmp_days"]
        if token in sel: sel.remove(token)
        else: sel.append(token)
        sel.sort(key=lambda d: DAYS_ORDER.index(d))
        await q.edit_message_reply_markup(reply_markup=days_multi_kb(sel))
    return CREATE_PHASE_DAYS

async def create_phase_time(update:Update, context:ContextTypes.DEFAULT_TYPE) -> int:
    try:
        p = update.message.text.strip().split(":")
        h,m = int(p[0]),int(p[1])
        if not (0<=h<=23 and 0<=m<=59): raise ValueError
        ts = f"{h:02d}:{m:02d}"
    except Exception:
        await update.message.reply_text("Неверный формат. Введи как *ЧЧ:ММ*, например `10:00`:", parse_mode="Markdown")
        return CREATE_PHASE_TIME

    c = context.user_data["c"]; pk = c["editing_phase"]
    existing = c["phases_config"].get(pk, {})
    c["phases_config"][pk] = {
        "days": c["tmp_days"], "time": ts,
        "muscles": dict(existing.get("muscles",{})),
        "exercises": dict(existing.get("exercises",{})),
    }
    c["tmp_muscles"]   = dict(c["phases_config"][pk]["muscles"])
    c["tmp_exercises"] = dict(c["phases_config"][pk]["exercises"])

    num = pk.replace("phase_","")
    ds = ", ".join(DAY_NAMES[d] for d in c["tmp_days"])
    await update.message.reply_text(
        f"✅ Фаза {num}: *{ds}* в *{ts}*\n\n"
        "*Шаг 3:* Для каждого дня укажи группу мышц и упражнения.\n\n"
        "📋 = группа мышц добавлена\n"
        "✅ = группа мышц + упражнения\n\n"
        "Нажми на день чтобы заполнить:",
        parse_mode="Markdown",
        reply_markup=muscle_day_kb(c["tmp_days"], c["tmp_muscles"], c["tmp_exercises"]),
    )
    return CREATE_MUSCLE_SEL

async def create_muscle_sel(update:Update, context:ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    if q.data == "menu:main": return await cmd_start(update, context)
    
    # Обработка кнопки Назад при создании
    if q.data.startswith("mday:back"):
        c = context.user_data["c"]
        n = c["phases"]
        await q.edit_message_text(
            "Выберите фазу для настройки:",
            reply_markup=create_phase_sel_kb(n, c["phases_config"])
        )
        return CREATE_PHASE_SEL
    
    c = context.user_data["c"]; token = q.data.split(":")[1]

    if token == "save":
        pk = c["editing_phase"]
        c["phases_config"][pk]["muscles"]   = c["tmp_muscles"]
        c["phases_config"][pk]["exercises"] = c["tmp_exercises"]
        num = pk.replace("phase_",""); n = c["phases"]
        await q.edit_message_text(
            f"✅ *Фаза {num} сохранена!*\n\nВыбери следующую фазу или сохрани тренировку:",
            parse_mode="Markdown",
            reply_markup=create_phase_sel_kb(n, c["phases_config"]),
        )
        return CREATE_PHASE_SEL

    day = token; c["tmp_muscle_day"] = day
    cur_m = c["tmp_muscles"].get(day,""); day_name = DAY_NAMES.get(day,day)
    text = f"💪 *{day_name}*\n\n"
    if cur_m: text += f"Текущая группа мышц: _{cur_m}_\n\n"
    text += "Введи *группу мышц* для этого дня\n_(например: Грудь + Трицепс)_:"
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=cancel_kb())
    return CREATE_MUSCLE_ENTER

async def create_muscle_enter(update:Update, context:ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    c = context.user_data["c"]; day = c.get("tmp_muscle_day","")
    if day: c["tmp_muscles"][day] = text

    cur_e = c["tmp_exercises"].get(day,""); day_name = DAY_NAMES.get(day,day)
    msg = f"✅ Группа мышц: *{text}*\n\n"
    if cur_e: msg += f"Текущие упражнения:\n_{cur_e[:200]}_\n\n"
    msg += f"Теперь введи *упражнения* для *{day_name}*\n_(каждое с новой строки)_:"
    await update.message.reply_text(
        msg, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭ Пропустить упражнения", callback_data="exer:skip")],
            [InlineKeyboardButton("❌ Отмена",                callback_data="menu:main")],
        ]),
    )
    return CREATE_EXERCISE_ENTER

async def create_exercise_enter(update:Update, context:ContextTypes.DEFAULT_TYPE) -> int:
    c = context.user_data["c"]; day = c.get("tmp_muscle_day","")
    if update.message:
        text = update.message.text.strip()
        if day: c["tmp_exercises"][day] = text
        day_name = DAY_NAMES.get(day,day)
        await update.message.reply_text(
            f"✅ *{day_name}* полностью заполнен!\n\nЗаполни остальные дни или сохрани фазу:",
            parse_mode="Markdown",
            reply_markup=muscle_day_kb(c["phases_config"][c["editing_phase"]]["days"],
                                       c["tmp_muscles"], c["tmp_exercises"]),
        )
    return CREATE_MUSCLE_SEL

async def create_exercise_skip(update:Update, context:ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    if q.data == "menu:main": return await cmd_start(update, context)
    c = context.user_data["c"]
    await q.edit_message_text(
        "Заполни остальные дни или сохрани фазу:",
        reply_markup=muscle_day_kb(c["phases_config"][c["editing_phase"]]["days"],
                                   c["tmp_muscles"], c["tmp_exercises"]),
    )
    return CREATE_MUSCLE_SEL

async def finalize_create(update:Update, context:ContextTypes.DEFAULT_TYPE) -> int:
    c = context.user_data["c"]; uid = update.effective_user.id
    workout = {"id": c["wid"], "name": c["name"], "phases": c["phases"], "phases_data": c["phases_config"]}
    upsert_workout(uid, workout)
    schedule_notifications(context.application, uid, workout)

    text = (
        f"🎉 *Тренировка создана!*\n\n"
        f"📋 *{workout['name']}*\n\n"
        f"✅ Всё готово к тренировкам!\n"
        f"⏰ Напоминания настроены"
    )
    context.user_data.clear()
    await send_or_edit(update, text, main_menu_kb())
    return MAIN_MENU
# ═══════════════════════ START WORKOUT ════════════════════════════════════════

async def sw_select(update:Update, context:ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    if q.data == "menu:main": return await cmd_start(update, context)
    
    # Обработка кнопки Назад
    if q.data == "sw:back":
        await q.edit_message_text("Главное меню", reply_markup=main_menu_kb())
        return MAIN_MENU
    
    wid = q.data.split(":")[1]
    ws = get_user_workouts(update.effective_user.id)
    w = next((x for x in ws if x["id"]==wid), None)
    if not w:
        await q.edit_message_text("Тренировка не найдена.", reply_markup=back_menu_kb()); return MAIN_MENU
    context.user_data["active"] = w
    done = [pk for pk,pv in w.get("phases_data",{}).items() if pv.get("days")]
    await q.edit_message_text(f"🏋️ *{w['name']}*\n\nВыбери фазу:", parse_mode="Markdown",
                              reply_markup=phase_select_kb(w["phases"],"sp",wid,done))
    return SW_PHASE

async def sw_phase(update:Update, context:ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    if q.data == "menu:main": return await cmd_start(update, context)
    
    # Обработка кнопки Назад
    if q.data == "sp:back":
        uid = update.effective_user.id
        ws = get_user_workouts(uid)
        await q.edit_message_text("🏋️ *Выбери тренировку:*", parse_mode="Markdown", reply_markup=workouts_kb(ws, "sw"))
        return SW_SELECT
    
    parts = q.data.split(":"); wid,pk = parts[1],parts[2]
    w = context.user_data.get("active")
    if not w: return await cmd_start(update, context)
    phase = w["phases_data"].get(pk,{}); context.user_data["active_phase"] = pk
    num = pk.replace("phase_","")
    await q.edit_message_text(
        f"🏋️ *{w['name']} — Фаза {num}*\n⏰ {phase.get('time','—')}\n\nВыбери день тренировки:",
        parse_mode="Markdown",
        reply_markup=workout_days_kb(phase.get("days",[]),"sd",wid,pk,phase.get("muscles",{})),
    )
    return SW_DAY

async def sw_day(update:Update, context:ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    if q.data == "menu:main": return await cmd_start(update, context)

    if q.data.startswith("wstart:"):
        parts = q.data.split(":")
        context.user_data["wstart"] = datetime.now().isoformat()
        # Убираем кнопки с сообщения-программы, оставляя текст видимым
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        # Отправляем новое сообщение с таймером
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(
            "⏹ Завершить тренировку",
            callback_data=f"wend:{parts[1]}:{parts[2]}:{parts[3]}"
        )]])
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=(
                "⏱️ *Тренировка началась!*\n\n"
                "⏰ Таймер запущен...\n"
                "💪 Удачной тренировки!\n\n"
                "Нажми кнопку ниже, когда закончишь:"
            ),
            parse_mode="Markdown",
            reply_markup=kb,
        )
        return SW_DAY

    if q.data.startswith("wend:"):
        si = context.user_data.get("wstart")
        if si:
            dur = datetime.now()-datetime.fromisoformat(si)
            mins,secs = int(dur.total_seconds()//60), int(dur.total_seconds()%60)
            dt = f"⏱ Длительность: *{mins} мин {secs} сек*\n\n"
        else: dt=""
        await q.edit_message_text(f"🎉 *Завершено!*\n\n{dt}Отличная работа! 💪",
                                  parse_mode="Markdown", reply_markup=main_menu_kb())
        return MAIN_MENU

    # Обработка кнопок Назад
    if q.data.startswith("sd:back:"):
        parts = q.data.split(":")
        wid = parts[2]
        
        if len(parts) == 4:  # sd:back:wid:pk - вернуться к дням
            pk = parts[3]
            w = context.user_data.get("active")
            if not w: return await cmd_start(update, context)
            phase = w["phases_data"].get(pk,{})
            await q.edit_message_text(
                f"🏋️ *{w['name']} — Фаза {pk.replace('phase_','')}*\n⏰ {phase.get('time','—')}\n\nВыбери день тренировки:",
                parse_mode="Markdown",
                reply_markup=workout_days_kb(phase.get("days",[]),"sd",wid,pk,phase.get("muscles",{}))
            )
            return SW_DAY
        else:  # sd:back:wid - вернуться к фазам
            w = context.user_data.get("active")
            if not w: return await cmd_start(update, context)
            done = [pk for pk,pv in w.get("phases_data",{}).items() if pv.get("days")]
            await q.edit_message_text(
                f"🏋️ *{w['name']}*\n\nВыбери фазу:",
                parse_mode="Markdown",
                reply_markup=phase_select_kb(w["phases"],"sp",wid,done)
            )
            return SW_PHASE

    parts = q.data.split(":"); wid,pk,day = parts[1],parts[2],parts[3]
    w = context.user_data.get("active")
    if not w: return await cmd_start(update, context)
    phase = w["phases_data"].get(pk,{})
    muscles   = phase.get("muscles",{}).get(day,"")
    exercises = phase.get("exercises",{}).get(day,"")
    num = pk.replace("phase_","")

    text  = f"🏋️ *{w['name']}*\n📊 Фаза {num} | 📅 {DAY_NAMES.get(day,day)} | ⏰ {phase.get('time','—')}\n\n"
    text += f"💪 *Группа мышц:*\n{muscles or '_не указана_'}\n\n"
    text += f"📝 *Упражнения:*\n{exercises or '_не добавлены_'}\n\n"
    text += "━━━━━━━━━━━━━━━━━\n"
    text += "Готов к тренировке?\n\n"
    text += "💧 Не забывай пить воду 2-3л! 💦"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Начать тренировку", callback_data=f"wstart:{wid}:{pk}:{day}")],
        [InlineKeyboardButton("◀️ К дням", callback_data=f"sd:back:{wid}:{pk}")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="menu:main")],
    ])
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    return SW_DAY

# ═══════════════════════ EDIT WORKOUT ══════════════════════════════════════════

async def ew_select(update:Update, context:ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    if q.data == "menu:main": return await cmd_start(update, context)
    
    # Обработка кнопки Назад
    if q.data == "ew:back":
        await q.edit_message_text("Главное меню", reply_markup=main_menu_kb())
        return MAIN_MENU
    
    wid = q.data.split(":")[1]
    ws = get_user_workouts(update.effective_user.id)
    w = next((x for x in ws if x["id"]==wid), None)
    if not w: return await cmd_start(update, context)
    context.user_data["editing"] = w
    return await show_edit_menu(update, context)

async def show_edit_menu(update:Update, context:ContextTypes.DEFAULT_TYPE) -> int:
    w = context.user_data.get("editing")
    if not w: return await cmd_start(update, context)
    text = f"✏️ *{w['name']}*\n\n{phase_summary(w)}\n\nЧто изменить?"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Переименовать",         callback_data="em:rename")],
        [InlineKeyboardButton("⚙️ Редактировать фазу",    callback_data="em:phases")],
        [InlineKeyboardButton("🗑 Удалить тренировку",    callback_data="em:delete")],
        [InlineKeyboardButton("◀️ К тренировкам",         callback_data="em:back")],
        [InlineKeyboardButton("🏠 Главное меню",          callback_data="menu:main")],
    ])
    await send_or_edit(update, text, kb)
    return EDIT_MENU

async def edit_menu_handler(update:Update, context:ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    if q.data == "menu:main": return await cmd_start(update, context)
    
    # Обработка кнопки Назад
    if q.data == "em:back":
        uid = update.effective_user.id
        ws = get_user_workouts(uid)
        await q.edit_message_text(
            "✏️ *Выбери тренировку:*",
            parse_mode="Markdown",
            reply_markup=workouts_kb(ws,"ew")
        )
        return EW_SELECT
    
    action = q.data.split(":")[1]; w = context.user_data.get("editing")
    if not w: return await cmd_start(update, context)

    if action == "rename":
        await q.edit_message_text(f"📝 Текущее: *{w['name']}*\n\nВведи новое название:",
                                  parse_mode="Markdown", reply_markup=cancel_kb())
        return EDIT_NAME

    if action == "phases":
        done = [pk for pk,pv in w.get("phases_data",{}).items() if pv.get("days")]
        await q.edit_message_text("⚙️ Выбери фазу для редактирования:", parse_mode="Markdown",
                                  reply_markup=phase_select_kb(w["phases"],"eph",w["id"],done))
        return EDIT_PHASE_SEL

    if action == "delete":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Да, удалить", callback_data="em:confirm_delete")],
            [InlineKeyboardButton("❌ Отмена",       callback_data="menu:main")],
        ])
        await q.edit_message_text(f"🗑 Удалить *{w['name']}*?\n\n⚠️ Нельзя отменить!",
                                  parse_mode="Markdown", reply_markup=kb)
        return EDIT_MENU

    if action == "confirm_delete":
        name = w["name"]; remove_workout(update.effective_user.id, w["id"])
        context.user_data.clear()
        await q.edit_message_text(f"🗑 *{name}* удалена.", parse_mode="Markdown", reply_markup=main_menu_kb())
        return MAIN_MENU

    return EDIT_MENU

async def edit_name(update:Update, context:ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip(); w = context.user_data.get("editing")
    if not name or not w: await update.message.reply_text("Введи название:"); return EDIT_NAME
    w["name"] = name; upsert_workout(update.effective_user.id, w)
    await update.message.reply_text(f"✅ Переименовано в *{name}*", parse_mode="Markdown", reply_markup=main_menu_kb())
    return MAIN_MENU

async def edit_phase_sel(update:Update, context:ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    if q.data == "menu:main": return await cmd_start(update, context)
    
    # Обработка кнопки Назад
    if q.data.startswith("eph:back"):
        w = context.user_data.get("editing")
        if not w: return await cmd_start(update, context)
        return await show_edit_menu(update, context)
    
    parts = q.data.split(":"); wid,pk = parts[1],parts[2]
    w = context.user_data.get("editing")
    if not w: return await cmd_start(update, context)
    phase = w["phases_data"].get(pk,{})
    context.user_data["edit_pk"] = pk
    num = pk.replace("phase_","")
    ds = ", ".join(DAY_NAMES.get(d,d) for d in phase.get("days",[])) or "не заданы"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Изменить дни",          callback_data="epm:days")],
        [InlineKeyboardButton("⏰ Изменить время",         callback_data="epm:time")],
        [InlineKeyboardButton("💪 Редактировать дни/мышцы/упражнения", callback_data="epm:muscles")],
        [InlineKeyboardButton("◀️ К фазам",               callback_data="epm:back")],
        [InlineKeyboardButton("🏠 Главное меню",          callback_data="menu:main")],
    ])
    await q.edit_message_text(
        f"⚙️ *Фаза {num}*\n📅 {ds} | ⏰ {phase.get('time','—')}\n\nЧто изменить?",
        parse_mode="Markdown", reply_markup=kb,
    )
    return EDIT_PHASE_MENU

async def edit_phase_menu(update:Update, context:ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    if q.data == "menu:main": return await cmd_start(update, context)
    action = q.data.split(":")[1]; w = context.user_data.get("editing")

    if action == "back":
        done = [pk for pk,pv in w.get("phases_data",{}).items() if pv.get("days")]
        await q.edit_message_text("⚙️ Выбери фазу:", parse_mode="Markdown",
                                  reply_markup=phase_select_kb(w["phases"],"eph",w["id"],done))
        return EDIT_PHASE_SEL

    pk = context.user_data.get("edit_pk"); phase = w["phases_data"].get(pk,{})

    if action == "days":
        context.user_data["edit_tmp_days"] = list(phase.get("days",[]))
        await q.edit_message_text("📅 Выбери новые дни:", reply_markup=days_multi_kb(context.user_data["edit_tmp_days"]))
        return EDIT_PHASE_DAYS

    if action == "time":
        await q.edit_message_text(f"⏰ Текущее: *{phase.get('time','—')}*\n\nВведи новое время (ЧЧ:ММ):",
                                  parse_mode="Markdown", reply_markup=cancel_kb())
        return EDIT_PHASE_TIME

    if action == "muscles":
        muscles   = phase.get("muscles",{})
        exercises = phase.get("exercises",{})
        context.user_data["edit_tmp_muscles"]   = dict(muscles)
        context.user_data["edit_tmp_exercises"] = dict(exercises)
        num = pk.replace("phase_","")
        await q.edit_message_text(
            f"💪 *Фаза {num}* — выбери день:\n\n"
            "📋 = есть группа мышц\n✅ = есть мышцы + упражнения",
            parse_mode="Markdown",
            reply_markup=muscle_day_kb(phase.get("days",[]), muscles, exercises),
        )
        return EDIT_MUSCLE_SEL

    return EDIT_PHASE_MENU

async def edit_phase_days(update:Update, context:ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    if q.data == "menu:main": return await cmd_start(update, context)
    token = q.data.split(":")[1]; sel = context.user_data.get("edit_tmp_days",[])
    w = context.user_data.get("editing"); pk = context.user_data.get("edit_pk")

    if token == "confirm":
        if not sel: await q.answer("Выбери хотя бы один день!", show_alert=True); return EDIT_PHASE_DAYS
        if pk not in w["phases_data"]: w["phases_data"][pk] = {"days": [], "time": "", "muscles": {}, "exercises": {}}
        w["phases_data"][pk]["days"] = sel
        upsert_workout(update.effective_user.id, w)
        schedule_notifications(context.application, update.effective_user.id, w)
        ds = ", ".join(DAY_NAMES[d] for d in sel)
        await q.edit_message_text(f"✅ Дни обновлены: *{ds}*", parse_mode="Markdown", reply_markup=main_menu_kb())
        return MAIN_MENU

    if token in DAYS_ORDER:
        if token in sel: sel.remove(token)
        else: sel.append(token)
        sel.sort(key=lambda d: DAYS_ORDER.index(d))
        context.user_data["edit_tmp_days"] = sel
        await q.edit_message_reply_markup(reply_markup=days_multi_kb(sel))
    return EDIT_PHASE_DAYS

async def edit_phase_time(update:Update, context:ContextTypes.DEFAULT_TYPE) -> int:
    try:
        p = update.message.text.strip().split(":"); h,m = int(p[0]),int(p[1])
        if not (0<=h<=23 and 0<=m<=59): raise ValueError
        ts = f"{h:02d}:{m:02d}"
    except Exception:
        await update.message.reply_text("Неверный формат. Введи как *ЧЧ:ММ*:", parse_mode="Markdown")
        return EDIT_PHASE_TIME
    w = context.user_data.get("editing"); pk = context.user_data.get("edit_pk")
    if w and pk:
        if pk not in w["phases_data"]: w["phases_data"][pk] = {"days": [], "time": "", "muscles": {}, "exercises": {}}
        w["phases_data"][pk]["time"] = ts
        upsert_workout(update.effective_user.id, w)
        schedule_notifications(context.application, update.effective_user.id, w)
    await update.message.reply_text(f"✅ Время обновлено: *{ts}*", parse_mode="Markdown", reply_markup=main_menu_kb())
    return MAIN_MENU

# ─── Edit: muscles + exercises ────────────────────────────────────────────────

async def edit_muscle_sel(update:Update, context:ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    if q.data == "menu:main": return await cmd_start(update, context)
    
    # Обработка кнопки Назад при редактировании
    if q.data.startswith("mday:back"):
        w = context.user_data.get("editing")
        pk = context.user_data.get("edit_pk")
        if not w or not pk: return await cmd_start(update, context)
        phase = w["phases_data"].get(pk,{})
        num = pk.replace("phase_","")
        ds = ", ".join(DAY_NAMES.get(d,d) for d in phase.get("days",[])) or "не заданы"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 Изменить дни",          callback_data="epm:days")],
            [InlineKeyboardButton("⏰ Изменить время",         callback_data="epm:time")],
            [InlineKeyboardButton("💪 Редактировать дни/мышцы/упражнения", callback_data="epm:muscles")],
            [InlineKeyboardButton("◀️ К фазам",               callback_data="epm:back")],
            [InlineKeyboardButton("🏠 Главное меню",          callback_data="menu:main")],
        ])
        await q.edit_message_text(
            f"⚙️ *Фаза {num}*\n📅 {ds} | ⏰ {phase.get('time','—')}\n\nЧто изменить?",
            parse_mode="Markdown", reply_markup=kb,
        )
        return EDIT_PHASE_MENU
    
    token = q.data.split(":")[1]; w = context.user_data.get("editing"); pk = context.user_data.get("edit_pk")

    if token == "save":
        if pk not in w["phases_data"]: w["phases_data"][pk] = {"days": [], "time": "", "muscles": {}, "exercises": {}}
        w["phases_data"][pk]["muscles"]   = context.user_data.get("edit_tmp_muscles",{})
        w["phases_data"][pk]["exercises"] = context.user_data.get("edit_tmp_exercises",{})
        upsert_workout(update.effective_user.id, w)
        await q.edit_message_text("✅ *Сохранено!*", parse_mode="Markdown", reply_markup=main_menu_kb())
        return MAIN_MENU

    # Day selected → show options
    day = token; context.user_data["edit_day"] = day; day_name = DAY_NAMES.get(day,day)
    muscles   = context.user_data.get("edit_tmp_muscles",{})
    exercises = context.user_data.get("edit_tmp_exercises",{})
    cur_m = muscles.get(day,""); cur_e = exercises.get(day,"")

    text = f"📅 *{day_name}*\n\n"
    text += f"💪 Мышцы: {cur_m or '_не заполнено_'}\n"
    text += f"📝 Упражнения: {'есть ✅' if cur_e else '_не добавлены_'}\n\n"
    text += "Что редактируешь?"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💪 Изменить группу мышц",  callback_data="edopt:muscles")],
        [InlineKeyboardButton("📝 Изменить упражнения",   callback_data="edopt:exercises")],
        [InlineKeyboardButton("◀️ Назад к дням",          callback_data="edopt:back")],
        [InlineKeyboardButton("🏠 Главное меню",          callback_data="menu:main")],
    ])
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    return EDIT_DAY_OPTS

async def edit_day_opts(update:Update, context:ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    if q.data == "menu:main": return await cmd_start(update, context)
    action = q.data.split(":")[1]; w = context.user_data.get("editing"); pk = context.user_data.get("edit_pk")
    day = context.user_data.get("edit_day","")

    if action == "back":
        phase = w["phases_data"].get(pk,{})
        m = context.user_data.get("edit_tmp_muscles",{})
        e = context.user_data.get("edit_tmp_exercises",{})
        await q.edit_message_text("💪 Выбери день:", reply_markup=muscle_day_kb(phase.get("days",[]),m,e))
        return EDIT_MUSCLE_SEL

    if action == "muscles":
        cur = context.user_data.get("edit_tmp_muscles",{}).get(day,"")
        text = f"💪 *{DAY_NAMES.get(day,day)}*\n\n"
        if cur: text += f"Сейчас: _{cur}_\n\n"
        text += "Введи новую группу мышц:"
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=cancel_kb())
        return EDIT_MUSCLE_ENTER

    if action == "exercises":
        cur = context.user_data.get("edit_tmp_exercises",{}).get(day,"")
        text = f"📝 *{DAY_NAMES.get(day,day)}*\n\n"
        if cur: text += f"Текущие упражнения:\n_{cur[:300]}_\n\n"
        text += "Введи новые упражнения (каждое с новой строки):"
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=cancel_kb())
        return EDIT_EXERCISE_ENTER

    return EDIT_DAY_OPTS

async def edit_muscle_enter(update:Update, context:ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip(); day = context.user_data.get("edit_day","")
    w = context.user_data.get("editing"); pk = context.user_data.get("edit_pk")
    muscles = context.user_data.get("edit_tmp_muscles",{})
    if day: muscles[day] = text; context.user_data["edit_tmp_muscles"] = muscles
    phase = w["phases_data"].get(pk,{})
    await update.message.reply_text(
        f"✅ Мышцы обновлены: *{text}*\n\nПродолжай или сохрани:",
        parse_mode="Markdown",
        reply_markup=muscle_day_kb(phase.get("days",[]), muscles, context.user_data.get("edit_tmp_exercises",{})),
    )
    return EDIT_MUSCLE_SEL

async def edit_exercise_enter(update:Update, context:ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip(); day = context.user_data.get("edit_day","")
    w = context.user_data.get("editing"); pk = context.user_data.get("edit_pk")
    exercises = context.user_data.get("edit_tmp_exercises",{})
    if day: exercises[day] = text; context.user_data["edit_tmp_exercises"] = exercises
    phase = w["phases_data"].get(pk,{})
    await update.message.reply_text(
        f"✅ Упражнения обновлены!\n\nПродолжай или сохрани:",
        parse_mode="Markdown",
        reply_markup=muscle_day_kb(phase.get("days",[]), context.user_data.get("edit_tmp_muscles",{}), exercises),
    )
    return EDIT_MUSCLE_SEL

# ─── Fallback ─────────────────────────────────────────────────────────────────
async def unknown_msg(update:Update, context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Используй /start", reply_markup=main_menu_kb())

# ─── Startup ──────────────────────────────────────────────────────────────────
async def on_startup(app:Application):
    logger.info("Rescheduling notifications...")
    for uid_str, ud in load_data().items():
        try: uid = int(uid_str)
        except ValueError: continue
        for w in ud.get("workouts",[]): schedule_notifications(app, uid, w)

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    if not BOT_TOKEN: logger.error("BOT_TOKEN not set!"); return
    app = Application.builder().token(BOT_TOKEN).post_init(on_startup).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        per_message=False,
        states={
            MAIN_MENU: [
                CallbackQueryHandler(main_menu_handler, pattern="^menu:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, button_only_handler),
            ],
            CREATE_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, create_name),
                CallbackQueryHandler(main_menu_handler, pattern="^menu:"),
            ],
            CREATE_PHASES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, create_phases),
                CallbackQueryHandler(main_menu_handler, pattern="^menu:"),
            ],
            CREATE_PHASE_SEL: [
                CallbackQueryHandler(create_phase_sel, pattern="^(cph:|menu:main)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, button_only_handler),
            ],
            CREATE_PHASE_DAYS: [
                CallbackQueryHandler(create_phase_days, pattern="^(day:|menu:main)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, button_only_handler),
            ],
            CREATE_PHASE_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, create_phase_time),
                CallbackQueryHandler(main_menu_handler, pattern="^menu:"),
            ],
            CREATE_MUSCLE_SEL: [
                CallbackQueryHandler(create_muscle_sel, pattern="^(mday:|menu:main)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, button_only_handler),
            ],
            CREATE_MUSCLE_ENTER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, create_muscle_enter),
                CallbackQueryHandler(main_menu_handler, pattern="^menu:"),
            ],
            CREATE_EXERCISE_ENTER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, create_exercise_enter),
                CallbackQueryHandler(create_exercise_skip, pattern="^(exer:|menu:main)"),
            ],
            SW_SELECT: [
                CallbackQueryHandler(sw_select, pattern="^(sw:|menu:main)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, button_only_handler),
            ],
            SW_PHASE: [
                CallbackQueryHandler(sw_phase, pattern="^(sp:|menu:main)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, button_only_handler),
            ],
            SW_DAY: [
                CallbackQueryHandler(sw_day, pattern="^(sd:|wstart:|wend:|menu:main)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, button_only_handler),
            ],
            EW_SELECT: [
                CallbackQueryHandler(ew_select, pattern="^(ew:|menu:main)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, button_only_handler),
            ],
            EDIT_MENU: [
                CallbackQueryHandler(edit_menu_handler, pattern="^(em:|menu:main)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, button_only_handler),
            ],
            EDIT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_name),
                CallbackQueryHandler(main_menu_handler, pattern="^menu:"),
            ],
            EDIT_PHASE_SEL: [
                CallbackQueryHandler(edit_phase_sel, pattern="^(eph:|menu:main)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, button_only_handler),
            ],
            EDIT_PHASE_MENU: [
                CallbackQueryHandler(edit_phase_menu, pattern="^(epm:|menu:main)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, button_only_handler),
            ],
            EDIT_PHASE_DAYS: [
                CallbackQueryHandler(edit_phase_days, pattern="^(day:|menu:main)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, button_only_handler),
            ],
            EDIT_PHASE_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_phase_time),
                CallbackQueryHandler(main_menu_handler, pattern="^menu:"),
            ],
            EDIT_MUSCLE_SEL: [
                CallbackQueryHandler(edit_muscle_sel, pattern="^(mday:|menu:main)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, button_only_handler),
            ],
            EDIT_DAY_OPTS: [
                CallbackQueryHandler(edit_day_opts, pattern="^(edopt:|menu:main)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, button_only_handler),
            ],
            EDIT_MUSCLE_ENTER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_muscle_enter),
                CallbackQueryHandler(main_menu_handler, pattern="^menu:"),
            ],
            EDIT_EXERCISE_ENTER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_exercise_enter),
                CallbackQueryHandler(main_menu_handler, pattern="^menu:"),
            ],
        },
        fallbacks=[
            CommandHandler("start", cmd_start),
            CallbackQueryHandler(main_menu_handler, pattern="^menu:main"),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_msg))
    logger.info("Starting bot...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
