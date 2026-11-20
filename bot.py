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
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE").strip()
ADMIN_IDS: set[int] = {
    123456789,  # O'zingizning Telegram ID raqamingizni yozing
}

DB_PATH = os.getenv("DB_PATH", "bot_database.db")
LOGO_PATH = os.getenv("LOGO_PATH", "logo.png")

DEFAULT_SECTIONS: list[str] = [
    "🇺🇿 O'zbekiston tarixi",
    "🕌 Dinshunoslik",
    "🧠 Falsafa",
    "📊 Pedagogik metodlar",
    "📚 adabiyotlar",
    "✍️ Ijodkor talabalar",
]

# ==========================================
# FLASK VEB-SERVER (RENDER 24/7 UCHUN)
# ==========================================
flask_app = Flask(__name__)


@flask_app.route("/")
def index():
    return "SamATI EduInfoBot is running!", 200


@flask_app.route("/health")
def health_check():
    return "OK", 200


def start_flask_server():
    port = int(os.getenv("PORT", "8080"))
    flask_app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
    )


# ==========================================
# SQLITE MA'LUMOTLAR BAZASI
# ==========================================
def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS custom_cells (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS materials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cell_name TEXT NOT NULL,
                text_content TEXT,
                file_id TEXT,
                file_name TEXT,
                content_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def get_custom_cells() -> list[str]:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT title FROM custom_cells ORDER BY id ASC")
        return [row["title"] for row in cur.fetchall()]


def get_all_sections() -> list[str]:
    custom = get_custom_cells()
    merged = list(DEFAULT_SECTIONS)
    for item in custom:
        if item not in merged:
            merged.append(item)
    return merged


def add_custom_cell(title: str) -> bool:
    clean_title = title.strip()
    if not clean_title:
        return False
    with get_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO custom_cells (title) VALUES (?)",
                (clean_title,),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def rename_custom_cell(old_title: str, new_title: str) -> bool:
    clean_new = new_title.strip()
    if not clean_new:
        return False
    with get_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE custom_cells SET title = ? WHERE title = ?",
                (clean_new, old_title),
            )
            cur.execute(
                "UPDATE materials SET cell_name = ? WHERE cell_name = ?",
                (clean_new, old_title),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def delete_custom_cell(title: str):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM materials WHERE cell_name = ?", (title,))
        cur.execute("DELETE FROM custom_cells WHERE title = ?", (title,))
        conn.commit()


def get_materials_by_cell(cell_name: str) -> list[sqlite3.Row]:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, cell_name, text_content, file_id, file_name, content_type
            FROM materials
            WHERE cell_name = ?
            ORDER BY id ASC
            """,
            (cell_name,),
        )
        return cur.fetchall()


def get_material_by_id(material_id: int) -> sqlite3.Row | None:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, cell_name, text_content, file_id, file_name, content_type
            FROM materials
            WHERE id = ?
            """,
            (material_id,),
        )
        return cur.fetchone()


def add_material(
    cell_name: str,
    text_content: str | None = None,
    file_id: str | None = None,
    file_name: str | None = None,
    content_type: str | None = None,
) -> int:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO materials (cell_name, text_content, file_id, file_name, content_type)
            VALUES (?, ?, ?, ?, ?)
            """,
            (cell_name, text_content, file_id, file_name, content_type),
        )
        conn.commit()
        return int(cur.lastrowid)


def update_material_text(material_id: int, new_text: str | None) -> bool:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE materials SET text_content = ? WHERE id = ?",
            (new_text, material_id),
        )
        conn.commit()
        return cur.rowcount > 0


def delete_material_by_id(material_id: int) -> bool:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM materials WHERE id = ?", (material_id,))
        conn.commit()
        return cur.rowcount > 0


# ==========================================
# FSM HOLATLARI
# ==========================================
class AdminStates(StatesGroup):
    waiting_new_cell_name = State()
    waiting_rename_cell_name = State()
    waiting_material_input = State()
    waiting_edit_material_text = State()


# ==========================================
# YORDAMCHI FUNKSIYALAR VA KLAVIATURALAR
# ==========================================
def is_admin(user_id: int | None) -> bool:
    return bool(user_id is not None and user_id in ADMIN_IDS)


def escape_or_none(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    return html.escape(value)


def build_main_menu(user_id: int | None) -> ReplyKeyboardMarkup:
    keyboard: list[list[KeyboardButton]] = []
    sections = get_all_sections()

    row: list[KeyboardButton] = []
    for section in sections:
        row.append(KeyboardButton(text=section))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    if is_admin(user_id):
        keyboard.append([KeyboardButton(text="➕ Yangi yacheyka qo'shish")])
        keyboard.append([KeyboardButton(text="🏠 Bosh menyu")])
    else:
        keyboard.append([KeyboardButton(text="🏠 Bosh menyu")])

    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def build_cancel_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
        resize_keyboard=True,
    )


def build_cell_admin_keyboard(cell_name: str, user_id: int | None) -> InlineKeyboardMarkup | None:
    if not is_admin(user_id):
        return None
    short_name = cell_name[:35]
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="➕ Ma'lumot qo'shish",
                callback_data=f"mat_add:{short_name}",
            ),
            InlineKeyboardButton(
                text="✏️ Nomini o'zgartirish",
                callback_data=f"cell_ren:{short_name}",
            ),
        ]
    ]
    if cell_name not in DEFAULT_SECTIONS:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🗑 Yacheykani o'chirish",
                    callback_data=f"cell_del:{short_name}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_material_item_keyboard(material_id: int, user_id: int | None) -> InlineKeyboardMarkup | None:
    if not is_admin(user_id):
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Matnni tahrirlash",
                    callback_data=f"mat_edit:{material_id}",
                ),
                InlineKeyboardButton(
                    text="🗑 O'chirish",
                    callback_data=f"mat_del:{material_id}",
                ),
            ]
        ]
    )


def resolve_full_section_name(short_or_full: str) -> str:
    sections = get_all_sections()
    if short_or_full in sections:
        return short_or_full
    for sec in sections:
        if sec.startswith(short_or_full) or sec[:35] == short_or_full:
            return sec
    return short_or_full


async def send_welcome_screen(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id if message.from_user else None
    full_name = html.escape(message.from_user.full_name if message.from_user else "Foydalanuvchi")

    caption = (
        f"<b>@SamAtiEduInfoBot ga hush kelibsiz</b>, {full_name}!\n\n"
        "O'quv materiallari, adabiyotlar va foydali bo'limlarni ko'rish uchun "
        "pastdagi menyudan kerakli bo'limni tanlang."
    )
    menu = build_main_menu(user_id)

    if LOGO_PATH and os.path.isfile(LOGO_PATH):
        try:
            await message.answer_photo(
                photo=FSInputFile(LOGO_PATH),
                caption=caption,
                reply_markup=menu,
            )
            return
        except Exception as exc:
            logging.warning("Logo rasmni yuborishda xatolik: %s", exc)

    await message.answer(caption, reply_markup=menu)


# ==========================================
# BOT VA DISPATCHER
# ==========================================
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher(storage=MemoryStorage())


@dp.message(Command("start"))
async def handle_start_command(message: Message, state: FSMContext):
    await send_welcome_screen(message, state)


@dp.message(F.text == "🏠 Bosh menyu")
async def handle_home_button(message: Message, state: FSMContext):
    await send_welcome_screen(message, state)


@dp.message(F.text == "❌ Bekor qilish")
async def handle_cancel_button(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id if message.from_user else None
    await message.answer(
        "Amal bekor qilindi.",
        reply_markup=build_main_menu(user_id),
    )


# --- YANGI YACHEYKA QO'SHISH ---
@dp.message(F.text == "➕ Yangi yacheyka qo'shish")
async def handle_add_cell_start(message: Message, state: FSMContext):
    user_id = message.from_user.id if message.from_user else None
    if not is_admin(user_id):
        await message.answer("Bu funksiya faqat administratorlar uchun.")
        return
    await state.set_state(AdminStates.waiting_new_cell_name)
    await message.answer(
        "Yangi yacheyka nomini kiriting (masalan: <code>📘 Informatika</code>):",
        reply_markup=build_cancel_menu(),
    )


@dp.message(AdminStates.waiting_new_cell_name)
async def handle_add_cell_save(message: Message, state: FSMContext):
    user_id = message.from_user.id if message.from_user else None
    raw_text = (message.text or "").strip()
    if not raw_text:
        await message.answer("Iltimos, yacheyka nomi uchun matn kiriting.")
        return

    created = add_custom_cell(raw_text)
    await state.clear()
    menu = build_main_menu(user_id)

    if created:
        await message.answer(
            f"✅ <b>{html.escape(raw_text)}</b> yacheykasi muvaffaqiyatli qo'shildi.",
            reply_markup=menu,
        )
    else:
        await message.answer(
            f"⚠️ <b>{html.escape(raw_text)}</b> nomli yacheyka allaqachon mavjud.",
            reply_markup=menu,
        )


# --- YACHEYKA NOMINI O'ZGARTIRISH ---
@dp.callback_query(F.data.startswith("cell_ren:"))
async def callback_rename_cell_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    short_name = callback.data.split(":", 1)[1]
    full_name = resolve_full_section_name(short_name)
    await state.set_state(AdminStates.waiting_rename_cell_name)
    await state.update_data(target_cell=full_name)

    await callback.message.answer(
        f"<b>{html.escape(full_name)}</b> uchun yangi nom kiriting:",
        reply_markup=build_cancel_menu(),
    )
    await callback.answer()


@dp.message(AdminStates.waiting_rename_cell_name)
async def handle_rename_cell_save(message: Message, state: FSMContext):
    user_id = message.from_user.id if message.from_user else None
    data = await state.get_data()
    old_name = data.get("target_cell", "")
    new_name = (message.text or "").strip()

    if not new_name:
        await message.answer("Yangi nom bo'sh bo'lmasligi kerak. Qayta kiriting:")
        return

    updated = rename_custom_cell(old_name, new_name)
    await state.clear()

    if updated:
        await message.answer(
            f"✅ Yacheyka nomi <b>{html.escape(old_name)}</b> -> <b>{html.escape(new_name)}</b> ga o'zgartirildi.",
            reply_markup=build_main_menu(user_id),
        )
    else:
        await message.answer(
            "⚠️ Bunday nomli yacheyka allaqachon mavjud yoki o'zgartirib bo'lmadi.",
            reply_markup=build_main_menu(user_id),
        )


# --- YACHEYKANI O'CHIRISH ---
@dp.callback_query(F.data.startswith("cell_del:"))
async def callback_delete_cell(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    short_name = callback.data.split(":", 1)[1]
    full_name = resolve_full_section_name(short_name)

    if full_name in DEFAULT_SECTIONS:
        await callback.answer("Asosiy bo'limlarni o'chirib bo'lmaydi.", show_alert=True)
        return

    delete_custom_cell(full_name)
    await callback.message.answer(
        f"🗑 <b>{html.escape(full_name)}</b> yacheykasi va unga tegishli materiallar o'chirildi.",
        reply_markup=build_main_menu(callback.from_user.id),
    )
    await callback.answer("O'chirildi")


# --- MATERIAL QO'SHISH ---
@dp.callback_query(F.data.startswith("mat_add:"))
async def callback_add_material_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    short_name = callback.data.split(":", 1)[1]
    full_name = resolve_full_section_name(short_name)
    await state.set_state(AdminStates.waiting_material_input)
    await state.update_data(target_cell=full_name)

    await callback.message.answer(
        f"<b>{html.escape(full_name)}</b> bo'limiga qo'shish uchun matn, rasm, video, "
        "taqdimot (<code>.pptx</code>), PDF hujjat yoki audio yuboring:",
        reply_markup=build_cancel_menu(),
    )
    await callback.answer()


@dp.message(AdminStates.waiting_material_input)
async def handle_add_material_save(message: Message, state: FSMContext):
    user_id = message.from_user.id if message.from_user else None
    data = await state.get_data()
    cell_name = data.get("target_cell", DEFAULT_SECTIONS[0])

    raw_text = message.caption if message.caption else message.text
    safe_text = escape_or_none(raw_text)

    file_id: str | None = None
    file_name: str | None = None
    content_type: str | None = None

    if message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name or "document"
        content_type = "document"
    elif message.photo:
        file_id = message.photo[-1].file_id
        file_name = "photo.jpg"
        content_type = "photo"
    elif message.video:
        file_id = message.video.file_id
        file_name = message.video.file_name or "video.mp4"
        content_type = "video"
    elif message.audio:
        file_id = message.audio.file_id
        file_name = message.audio.file_name or "audio.mp3"
        content_type = "audio"
    elif message.voice:
        file_id = message.voice.file_id
        file_name = "voice.ogg"
        content_type = "voice"

    if not safe_text and not file_id:
        await message.answer(
            "Iltimos, matn yoki fayl (rasm, video, hujjat, taqdimot, audio) yuboring."
        )
        return

    add_material(
        cell_name=cell_name,
        text_content=safe_text,
        file_id=file_id,
        file_name=file_name,
        content_type=content_type,
    )
    await state.clear()

    await message.answer(
        f"✅ Ma'lumot <b>{html.escape(cell_name)}</b> bo'limiga muvaffaqiyatli saqlandi.",
        reply_markup=build_main_menu(user_id),
    )


# --- MATERIAL MATNINI TAHRIRLASH ---
@dp.callback_query(F.data.startswith("mat_edit:"))
async def callback_edit_material_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    raw_id = callback.data.split(":", 1)[1]
    if not raw_id.isdigit():
        await callback.answer("Noto'g'ri ID", show_alert=True)
        return

    mat_id = int(raw_id)
    material = get_material_by_id(mat_id)
    if not material:
        await callback.answer("Material topilmadi", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_edit_material_text)
    await state.update_data(material_id=mat_id)

    await callback.message.answer(
        f"Material <b>#{mat_id}</b> uchun yangi matn yoki izoh kiriting:",
        reply_markup=build_cancel_menu(),
    )
    await callback.answer()


@dp.message(AdminStates.waiting_edit_material_text)
async def handle_edit_material_save(message: Message, state: FSMContext):
    user_id = message.from_user.id if message.from_user else None
    data = await state.get_data()
    mat_id = data.get("material_id")
    new_raw = (message.text or "").strip()

    if not mat_id or not new_raw:
        await message.answer("Iltimos, yangi matnni kiriting.")
        return

    updated = update_material_text(int(mat_id), html.escape(new_raw))
    await state.clear()

    if updated:
        await message.answer(
            f"✅ Material <b>#{mat_id}</b> matni yangilandi.",
            reply_markup=build_main_menu(user_id),
        )
    else:
        await message.answer(
            "⚠️ Materialni yangilashda xatolik yuz berdi.",
            reply_markup=build_main_menu(user_id),
        )


# --- MATERIALNI O'CHIRISH ---
@dp.callback_query(F.data.startswith("mat_del:"))
async def callback_delete_material(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    raw_id = callback.data.split(":", 1)[1]
    if not raw_id.isdigit():
        await callback.answer("Noto'g'ri ID", show_alert=True)
        return

    mat_id = int(raw_id)
    deleted = delete_material_by_id(mat_id)
    if deleted:
        try:
            await callback.message.delete()
        except Exception:
            await callback.message.answer(f"🗑 Material <b>#{mat_id}</b> o'chirildi.")
        await callback.answer("O'chirildi")
    else:
        await callback.answer("Allaqachon o'chirilgan", show_alert=True)


# --- BO'LIM / YACHEYKA MATERIALLARINI KO'RSATISH ---
@dp.message(F.text)
async def handle_section_selection(message: Message):
    section_name = (message.text or "").strip()
    all_sections = get_all_sections()
    if section_name not in all_sections:
        return

    user_id = message.from_user.id if message.from_user else None
    materials = get_materials_by_cell(section_name)
    admin_kb = build_cell_admin_keyboard(section_name, user_id)

    if not materials:
        await message.answer(
            f"📌 <b>{html.escape(section_name)}</b>\n\n"
            "⚠️ Ushbu bo'limga hali ma'lumot kiritilmagan.",
            reply_markup=admin_kb,
        )
        return

    await message.answer(
        f"📌 <b>{html.escape(section_name)}</b> bo'limidagi materiallar:",
        reply_markup=admin_kb,
    )

    for row in materials:
        mat_id = row["id"]
        text_val = row["text_content"] or ""
        file_id = row["file_id"]
        content_type = row["content_type"]
        item_kb = build_material_item_keyboard(mat_id, user_id)

        if content_type == "photo" and file_id:
            await message.answer_photo(
                photo=file_id,
                caption=text_val or None,
                reply_markup=item_kb,
            )
        elif content_type == "video" and file_id:
            await message.answer_video(
                video=file_id,
                caption=text_val or None,
                reply_markup=item_kb,
            )
        elif content_type == "audio" and file_id:
            await message.answer_audio(
                audio=file_id,
                caption=text_val or None,
                reply_markup=item_kb,
            )
        elif content_type == "voice" and file_id:
            await message.answer_voice(
                voice=file_id,
                caption=text_val or None,
                reply_markup=item_kb,
            )
        elif content_type == "document" and file_id:
            await message.answer_document(
                document=file_id,
                caption=text_val or None,
                reply_markup=item_kb,
            )
        elif text_val:
            await message.answer(
                text_val,
                reply_markup=item_kb,
            )


# ==========================================
# ASOSIY ISHGA TUSHIRISH NUQTASI
# ==========================================
async def run_bot_polling():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        raise RuntimeError(
            "BOT_TOKEN o'rnatilmagan! Kod ichida BOT_TOKEN ni yozing yoki Render Environment'ga qo'shing."
        )

    init_database()
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("SamATI EduInfoBot polling rejimida ishga tushdi...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


def main():
    flask_thread = Thread(target=start_flask_server, name="FlaskThread", daemon=True)
    flask_thread.start()
    asyncio.run(run_bot_polling())


if __name__ == "__main__":
    main()