import os
import html
import sqlite3
import asyncio
import logging
from threading import Thread

from flask import Flask
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    FSInputFile,
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# ==========================================
# KONFIGURATSIYA
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8101370403:AAE2BYvdJbvtcih_A1za5jc-RSDz9zr92K8").strip()
ADMIN_IDS: set[int] = {
    7193226157 , 1013283682  # O'zingizning Telegram ID raqamingizni yozing
}

DB_PATH = os.getenv("DB_PATH", "bot_database.db")
LOGO_PATH = os.getenv("LOGO_PATH", "logo.png")

MAIN_MENU_ITEMS: list[str] = [
    "🇺🇿 O'zbekiston tarixi",
    "🕌 Dinshunoslik",
    "🧠 Falsafa",
    "📊 Pedagogik metodlar",
    "📚 adabiyotlar",
    "✍️ Ijodkor talabalar",
    "Qo'shimcha adabiyotlar",
    "O'zbekiston tarixi adabiyotlar",
    "Falsafa adabiyotlar",
    "Dinshunoslik adabiyotlar",
    "Izohli lug'at",
    "Video darslar",
    "Namunaviy darslar",
    "Loyiha muallifi",
]

DEFAULT_STAGES: list[str] = [
    "1-bosqich",
    "2-bosqich",
    "3-bosqich",
    "4-bosqich",
]

SUBJECTS_WITH_STAGES: set[str] = {
    "🇺🇿 O'zbekiston tarixi",
    "🕌 Dinshunoslik",
    "🧠 Falsafa",
}

STAGE_SEP = " :: "


def make_stage_key(subject: str, stage: str) -> str:
    return f"{subject}{STAGE_SEP}{stage}"


def is_stage_key(key: str) -> bool:
    return STAGE_SEP in key


# ==========================================
# FLASK SERVER (RENDER UCHUN)
# ==========================================
flask_app = Flask(__name__)


@flask_app.route("/")
def home():
    return "SamATI Gumanitar fanlar bot is running!", 200


@flask_app.route("/health")
def health():
    return "OK", 200


def run_flask():
    port = int(os.getenv("PORT", "8080"))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


# ==========================================
# SQLITE BAZA
# ==========================================
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS custom_sections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT UNIQUE NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS custom_stages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_name TEXT NOT NULL,
                stage_name TEXT NOT NULL,
                UNIQUE(subject_name, stage_name)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS materials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                section_key TEXT NOT NULL,
                text_content TEXT,
                file_id TEXT,
                file_name TEXT,
                content_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def get_custom_sections() -> list[str]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT title FROM custom_sections ORDER BY id ASC")
        return [r["title"] for r in cur.fetchall()]


def get_custom_stages(subject_name: str) -> list[str]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT stage_name FROM custom_stages WHERE subject_name = ? ORDER BY id ASC",
            (subject_name,),
        )
        return [r["stage_name"] for r in cur.fetchall()]


def get_all_stages_for_subject(subject_name: str) -> list[str]:
    stages = list(DEFAULT_STAGES)
    for st in get_custom_stages(subject_name):
        if st not in stages:
            stages.append(st)
    return stages


def get_all_main_sections() -> list[str]:
    result = list(MAIN_MENU_ITEMS)
    for item in get_custom_sections():
        if item not in result:
            result.append(item)
    return result


def add_custom_section(title: str) -> bool:
    clean = title.strip()
    if not clean:
        return False
    with get_conn() as conn:
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO custom_sections (title) VALUES (?)", (clean,))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def add_custom_stage(subject_name: str, stage_name: str) -> bool:
    clean_stage = stage_name.strip()
    if not clean_stage or clean_stage in DEFAULT_STAGES:
        return False
    with get_conn() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO custom_stages (subject_name, stage_name) VALUES (?, ?)",
                (subject_name, clean_stage),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def rename_custom_section(old_title: str, new_title: str) -> bool:
    clean = new_title.strip()
    if not clean:
        return False
    with get_conn() as conn:
        cur = conn.cursor()
        try:
            cur.execute("UPDATE custom_sections SET title = ? WHERE title = ?", (clean, old_title))
            cur.execute("UPDATE materials SET section_key = ? WHERE section_key = ?", (clean, old_title))
            conn.commit()
            return cur.rowcount > 0
        except sqlite3.IntegrityError:
            return False


def rename_custom_stage(subject_name: str, old_stage: str, new_stage: str) -> bool:
    clean_new = new_stage.strip()
    if not clean_new or old_stage in DEFAULT_STAGES or clean_new in DEFAULT_STAGES:
        return False
    old_key = make_stage_key(subject_name, old_stage)
    new_key = make_stage_key(subject_name, clean_new)
    with get_conn() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE custom_stages SET stage_name = ? WHERE subject_name = ? AND stage_name = ?",
                (clean_new, subject_name, old_stage),
            )
            cur.execute(
                "UPDATE materials SET section_key = ? WHERE section_key = ?",
                (new_key, old_key),
            )
            conn.commit()
            return cur.rowcount > 0
        except sqlite3.IntegrityError:
            return False


def delete_custom_section(title: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM materials WHERE section_key = ?", (title,))
        cur.execute("DELETE FROM custom_sections WHERE title = ?", (title,))
        conn.commit()


def delete_custom_stage(subject_name: str, stage_name: str):
    key = make_stage_key(subject_name, stage_name)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM materials WHERE section_key = ?", (key,))
        cur.execute(
            "DELETE FROM custom_stages WHERE subject_name = ? AND stage_name = ?",
            (subject_name, stage_name),
        )
        conn.commit()


def is_deletable_target(target_key: str) -> bool:
    if target_key in get_custom_sections():
        return True
    if is_stage_key(target_key):
        subj, st = target_key.split(STAGE_SEP, 1)
        return st in get_custom_stages(subj)
    return False


def get_all_manageable_targets() -> list[str]:
    targets: list[str] = []
    for sec in get_all_main_sections():
        if sec in SUBJECTS_WITH_STAGES:
            for st in get_all_stages_for_subject(sec):
                targets.append(make_stage_key(sec, st))
        else:
            targets.append(sec)
    return targets


def add_material(
    section_key: str,
    text_content: str | None = None,
    file_id: str | None = None,
    file_name: str | None = None,
    content_type: str | None = None,
):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO materials (section_key, text_content, file_id, file_name, content_type)
            VALUES (?, ?, ?, ?, ?)
            """,
            (section_key, text_content, file_id, file_name, content_type),
        )
        conn.commit()


def get_materials(section_key: str) -> list[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, section_key, text_content, file_id, file_name, content_type
            FROM materials
            WHERE section_key = ?
            ORDER BY id ASC
            """,
            (section_key,),
        )
        return cur.fetchall()


def delete_material(mat_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM materials WHERE id = ?", (mat_id,))
        conn.commit()
        return cur.rowcount > 0


# ==========================================
# FSM HOLATLARI
# ==========================================
class AdminStates(StatesGroup):
    waiting_new_section = State()
    waiting_new_stage = State()
    waiting_rename_target = State()
    waiting_material_content = State()


# ==========================================
# KLAVIATURALAR VA YORDAMCHI FUNKSIYALAR
# ==========================================
def is_admin(user_id: int | None) -> bool:
    return bool(user_id is not None and user_id in ADMIN_IDS)


def build_main_keyboard(user_id: int | None) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = []
    sections = get_all_main_sections()

    pair: list[KeyboardButton] = []
    for sec in sections:
        pair.append(KeyboardButton(text=sec))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)

    if is_admin(user_id):
        rows.append([KeyboardButton(text="Ma'lumot qo'shish/o'zgartirish")])
        rows.append([KeyboardButton(text="➕ Yangi yacheyka qo'shish")])

    rows.append([KeyboardButton(text="🏠 Bosh menyu")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def build_stages_keyboard(subject_name: str, user_id: int | None) -> ReplyKeyboardMarkup:
    stages = get_all_stages_for_subject(subject_name)
    rows: list[list[KeyboardButton]] = []

    pair: list[KeyboardButton] = []
    for st in stages:
        pair.append(KeyboardButton(text=st))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)

    if is_admin(user_id):
        rows.append([KeyboardButton(text="➕ Yangi bosqich/yacheyka qo'shish")])
        rows.append([KeyboardButton(text="Ma'lumot qo'shish/o'zgartirish")])

    rows.append([KeyboardButton(text="🏠 Bosh menyu")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def build_cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
        resize_keyboard=True,
    )


def build_admin_manage_inline() -> InlineKeyboardMarkup:
    targets = get_all_manageable_targets()
    buttons: list[list[InlineKeyboardButton]] = []
    for idx, name in enumerate(targets):
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"Tahrirlash: {name[:36]}",
                    callback_data=f"adm_pick:{idx}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_target_actions_inline(target_key: str, idx: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="➕ Ma'lumot qo'shish",
                callback_data=f"adm_add:{idx}",
            ),
            InlineKeyboardButton(
                text="✏️ Nomini o'zgartirish",
                callback_data=f"adm_ren:{idx}",
            ),
        ]
    ]
    if is_deletable_target(target_key):
        rows.append(
            [
                InlineKeyboardButton(
                    text="🗑 O'chirish",
                    callback_data=f"adm_del:{idx}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_start_menu(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id if message.from_user else None
    uname = html.escape(message.from_user.full_name if message.from_user else "Foydalanuvchi")
    caption = (
        f"<b>SamATI Gumanitar fanlar</b> botiga xush kelibsiz, {uname}!\n\n"
        "Kerakli fan, bosqich yoki bo'limni pastdagi menyudan tanlang."
    )
    kb = build_main_keyboard(uid)
    if LOGO_PATH and os.path.isfile(LOGO_PATH):
        try:
            await message.answer_photo(photo=FSInputFile(LOGO_PATH), caption=caption, reply_markup=kb)
            return
        except Exception as exc:
            logging.warning("Logo yuborishda xatolik: %s", exc)
    await message.answer(caption, reply_markup=kb)


async def send_section_materials(message: Message, section_key: str, display_title: str):
    uid = message.from_user.id if message.from_user else None
    materials = get_materials(section_key)
    if not materials:
        await message.answer(
            f"📌 <b>{html.escape(display_title)}</b>\n\n"
            "Ushbu bo'lim/bosqichga hali ma'lumot kiritilmagan."
        )
        return

    await message.answer(f"📌 <b>{html.escape(display_title)}</b> materiallari:")
    for row in materials:
        text_val = row["text_content"] or ""
        file_id = row["file_id"]
        ctype = row["content_type"]
        del_kb = (
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"mat_rm:{row['id']}")]
                ]
            )
            if is_admin(uid)
            else None
        )

        if ctype == "photo" and file_id:
            await message.answer_photo(photo=file_id, caption=text_val or None, reply_markup=del_kb)
        elif ctype == "video" and file_id:
            await message.answer_video(video=file_id, caption=text_val or None, reply_markup=del_kb)
        elif ctype == "audio" and file_id:
            await message.answer_audio(audio=file_id, caption=text_val or None, reply_markup=del_kb)
        elif ctype == "document" and file_id:
            await message.answer_document(document=file_id, caption=text_val or None, reply_markup=del_kb)
        elif text_val:
            await message.answer(text_val, reply_markup=del_kb)


# ==========================================
# BOT VA HANDLERLAR
# ==========================================
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())


@dp.message(Command("start"))
async def on_start(message: Message, state: FSMContext):
    await send_start_menu(message, state)


@dp.message(F.text == "🏠 Bosh menyu")
async def on_home(message: Message, state: FSMContext):
    await send_start_menu(message, state)


@dp.message(F.text == "❌ Bekor qilish")
async def on_cancel(message: Message, state: FSMContext):
    data = await state.get_data()
    active_subject = data.get("active_subject")
    await state.clear()
    uid = message.from_user.id if message.from_user else None

    if active_subject in SUBJECTS_WITH_STAGES:
        await state.update_data(active_subject=active_subject)
        await message.answer(
            "Amal bekor qilindi.",
            reply_markup=build_stages_keyboard(active_subject, uid),
        )
    else:
        await message.answer(
            "Amal bekor qilindi.",
            reply_markup=build_main_keyboard(uid),
        )


@dp.message(F.text == "➕ Yangi bosqich/yacheyka qo'shish")
async def on_new_stage_start(message: Message, state: FSMContext):
    uid = message.from_user.id if message.from_user else None
    if not is_admin(uid):
        await message.answer("Bu funksiya faqat administrator uchun.")
        return

    data = await state.get_data()
    active_subject = data.get("active_subject")
    if active_subject not in SUBJECTS_WITH_STAGES:
        await message.answer(
            "Avval O'zbekiston tarixi, Dinshunoslik yoki Falsafa bo'limiga kiring.",
            reply_markup=build_main_keyboard(uid),
        )
        return

    await state.set_state(AdminStates.waiting_new_stage)
    await message.answer(
        f"<b>{html.escape(active_subject)}</b> ichiga qo'shiladigan yangi bosqich/yacheyka nomini kiriting (masalan: <code>5-bosqich</code>):",
        reply_markup=build_cancel_keyboard(),
    )


@dp.message(AdminStates.waiting_new_stage)
async def on_new_stage_save(message: Message, state: FSMContext):
    uid = message.from_user.id if message.from_user else None
    data = await state.get_data()
    active_subject = data.get("active_subject")
    stage_title = (message.text or "").strip()

    if not stage_title:
        await message.answer("Nom bo'sh bo'lmasin.")
        return

    if active_subject not in SUBJECTS_WITH_STAGES:
        await state.clear()
        await message.answer("Fan topilmadi.", reply_markup=build_main_keyboard(uid))
        return

    created = add_custom_stage(active_subject, stage_title)
    await state.set_state(None)
    await state.update_data(active_subject=active_subject)

    if created:
        await message.answer(
            f"✅ <b>{html.escape(active_subject)}</b> ichiga <b>{html.escape(stage_title)}</b> qo'shildi.",
            reply_markup=build_stages_keyboard(active_subject, uid),
        )
    else:
        await message.answer(
            f"⚠️ <b>{html.escape(stage_title)}</b> allaqachon mavjud yoki standart bosqich nomi.",
            reply_markup=build_stages_keyboard(active_subject, uid),
        )


@dp.message(F.text == "Ma'lumot qo'shish/o'zgartirish")
async def on_admin_manage_menu(message: Message, state: FSMContext):
    data = await state.get_data()
    active_subject = data.get("active_subject")
    await state.clear()
    if active_subject:
        await state.update_data(active_subject=active_subject)

    uid = message.from_user.id if message.from_user else None
    if not is_admin(uid):
        await message.answer("Bu bo'lim faqat administrator uchun.")
        return

    await message.answer(
        "Qaysi bo'lim, bosqich yoki yacheykani boshqarasiz?",
        reply_markup=build_admin_manage_inline(),
    )


@dp.callback_query(F.data.startswith("adm_pick:"))
async def on_adm_pick(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    idx = int(callback.data.split(":", 1)[1])
    targets = get_all_manageable_targets()
    if idx < 0 or idx >= len(targets):
        await callback.answer("Topilmadi", show_alert=True)
        return
    target = targets[idx]
    await callback.message.edit_text(
        f"Tanlandi: <b>{html.escape(target)}</b>",
        reply_markup=build_target_actions_inline(target, idx),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("adm_add:"))
async def on_adm_add(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    idx = int(callback.data.split(":", 1)[1])
    targets = get_all_manageable_targets()
    if idx < 0 or idx >= len(targets):
        await callback.answer("Topilmadi", show_alert=True)
        return
    target = targets[idx]
    await state.set_state(AdminStates.waiting_material_content)
    await state.update_data(target_section=target)
    await callback.message.answer(
        f"<b>{html.escape(target)}</b> uchun matn, rasm, video, hujjat yoki audio yuboring:",
        reply_markup=build_cancel_keyboard(),
    )
    await callback.answer()


@dp.message(AdminStates.waiting_material_content)
async def on_save_material(message: Message, state: FSMContext):
    uid = message.from_user.id if message.from_user else None
    data = await state.get_data()
    section_key = data.get("target_section", MAIN_MENU_ITEMS[0])
    active_subject = data.get("active_subject")

    raw_text = message.caption if message.caption else message.text
    safe_text = html.escape(raw_text) if raw_text else None

    file_id = None
    file_name = None
    ctype = None

    if message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name or "document"
        ctype = "document"
    elif message.photo:
        file_id = message.photo[-1].file_id
        file_name = "photo.jpg"
        ctype = "photo"
    elif message.video:
        file_id = message.video.file_id
        file_name = message.video.file_name or "video.mp4"
        ctype = "video"
    elif message.audio:
        file_id = message.audio.file_id
        file_name = message.audio.file_name or "audio.mp3"
        ctype = "audio"

    if not safe_text and not file_id:
        await message.answer("Iltimos, matn yoki fayl yuboring.")
        return

    add_material(section_key, safe_text, file_id, file_name, ctype)
    await state.clear()
    if active_subject:
        await state.update_data(active_subject=active_subject)

    kb = (
        build_stages_keyboard(active_subject, uid)
        if active_subject in SUBJECTS_WITH_STAGES
        else build_main_keyboard(uid)
    )
    await message.answer(
        f"✅ Ma'lumot <b>{html.escape(section_key)}</b> ga saqlandi.",
        reply_markup=kb,
    )


@dp.callback_query(F.data.startswith("adm_ren:"))
async def on_adm_ren(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    idx = int(callback.data.split(":", 1)[1])
    targets = get_all_manageable_targets()
    if idx < 0 or idx >= len(targets):
        await callback.answer("Topilmadi", show_alert=True)
        return
    target = targets[idx]
    await state.set_state(AdminStates.waiting_rename_target)
    await state.update_data(rename_target_key=target)
    await callback.message.answer(
        f"<b>{html.escape(target)}</b> uchun yangi nom kiriting:",
        reply_markup=build_cancel_keyboard(),
    )
    await callback.answer()


@dp.message(AdminStates.waiting_rename_target)
async def on_save_rename(message: Message, state: FSMContext):
    uid = message.from_user.id if message.from_user else None
    data = await state.get_data()
    target_key = data.get("rename_target_key", "")
    active_subject = data.get("active_subject")
    new_title = (message.text or "").strip()

    if not new_title:
        await message.answer("Yangi nom bo'sh bo'lmasin.")
        return

    ok = False
    if is_stage_key(target_key):
        subj, old_st = target_key.split(STAGE_SEP, 1)
        ok = rename_custom_stage(subj, old_st, new_title)
    else:
        ok = rename_custom_section(target_key, new_title)

    await state.clear()
    if active_subject:
        await state.update_data(active_subject=active_subject)

    kb = (
        build_stages_keyboard(active_subject, uid)
        if active_subject in SUBJECTS_WITH_STAGES
        else build_main_keyboard(uid)
    )
    if ok:
        await message.answer(
            f"✅ Nomi <b>{html.escape(new_title)}</b> ga o'zgartirildi.",
            reply_markup=kb,
        )
    else:
        await message.answer(
            "⚠️ Standart bo'lim/bosqich nomini o'zgartirib bo'lmaydi yoki bunday nom allaqachon bor.",
            reply_markup=kb,
        )


@dp.callback_query(F.data.startswith("adm_del:"))
async def on_adm_del(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    idx = int(callback.data.split(":", 1)[1])
    targets = get_all_manageable_targets()
    if idx < 0 or idx >= len(targets):
        await callback.answer("Topilmadi", show_alert=True)
        return
    target = targets[idx]
    if not is_deletable_target(target):
        await callback.answer("Asosiy bo'lim yoki 1-4 bosqichni o'chirib bo'lmaydi", show_alert=True)
        return

    if is_stage_key(target):
        subj, st = target.split(STAGE_SEP, 1)
        delete_custom_stage(subj, st)
        data = await state.get_data()
        active_subject = data.get("active_subject")
        if active_subject == subj:
            await callback.message.answer(
                f"🗑 <b>{html.escape(target)}</b> o'chirildi.",
                reply_markup=build_stages_keyboard(subj, callback.from_user.id),
            )
    else:
        delete_custom_section(target)
        await callback.message.answer(
            f"🗑 <b>{html.escape(target)}</b> o'chirildi.",
            reply_markup=build_main_keyboard(callback.from_user.id),
        )

    await callback.message.edit_text(f"🗑 <b>{html.escape(target)}</b> o'chirildi.")
    await callback.answer("O'chirildi")


@dp.callback_query(F.data.startswith("mat_rm:"))
async def on_mat_rm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    mat_id = int(callback.data.split(":", 1)[1])
    if delete_material(mat_id):
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.answer("O'chirildi")
    else:
        await callback.answer("Topilmadi", show_alert=True)


@dp.message(F.text == "➕ Yangi yacheyka qo'shish")
async def on_new_cell_start(message: Message, state: FSMContext):
    uid = message.from_user.id if message.from_user else None
    if not is_admin(uid):
        await message.answer("Bu funksiya faqat administrator uchun.")
        return
    await state.set_state(AdminStates.waiting_new_section)
    await message.answer("Yangi yacheyka nomini kiriting:", reply_markup=build_cancel_keyboard())


@dp.message(AdminStates.waiting_new_section)
async def on_new_cell_save(message: Message, state: FSMContext):
    uid = message.from_user.id if message.from_user else None
    title = (message.text or "").strip()
    if not title:
        await message.answer("Nom bo'sh bo'lmasin.")
        return
    created = add_custom_section(title)
    await state.clear()
    if created:
        await message.answer(
            f"✅ <b>{html.escape(title)}</b> yacheykasi qo'shildi.",
            reply_markup=build_main_keyboard(uid),
        )
    else:
        await message.answer(
            f"⚠️ <b>{html.escape(title)}</b> allaqachon mavjud.",
            reply_markup=build_main_keyboard(uid),
        )


@dp.message(F.text)
async def on_menu_or_stage_click(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    uid = message.from_user.id if message.from_user else None

    if text in SUBJECTS_WITH_STAGES:
        await state.update_data(active_subject=text)
        await message.answer(
            f"<b>{html.escape(text)}</b> — bosqichni tanlang:",
            reply_markup=build_stages_keyboard(text, uid),
        )
        return

    data = await state.get_data()
    active_subject = data.get("active_subject")
    if active_subject in SUBJECTS_WITH_STAGES and text in get_all_stages_for_subject(active_subject):
        key = make_stage_key(active_subject, text)
        title = f"{active_subject} — {text}"
        await send_section_materials(message, key, title)
        return

    if text in get_all_main_sections():
        await state.update_data(active_subject=None)
        await send_section_materials(message, text, text)


# ==========================================
# ISHGA TUSHIRISH
# ==========================================
async def start_bot():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN topilmadi! Render Environment'da BOT_TOKEN ni kiriting.")
    init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("SamATI Gumanitar fanlar boti ishga tushdi...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


def main():
    Thread(target=run_flask, daemon=True).start()
    asyncio.run(start_bot())


if __name__ == "__main__":
    main()