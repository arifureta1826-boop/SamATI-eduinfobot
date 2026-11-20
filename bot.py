import os
import html
import sqlite3
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    FSInputFile
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

# Render'da 24/7 ishlashi uchun kichik veb-server (Flask)
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Bot 24/7 ishlayapti!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()


TOKEN = "8101370403:AAH_ESL3aaa28PfBaBXyBw0EJQKDP3GIEDQ"

# Adminlarning Telegram ID raqamlari ro'yxati
ADMIN_IDS = [7193226157, 1013283682]

LOGO_PATH = "logo.png"
WELCOME_TEXT = "@SamAtiEduInfoBot ga hush kelibsiz\n\n📚 Kerakli bo'limni pastdagi tugmalardan tanlang:"
MAX_MSG_LEN = 4000

bot = Bot(token=TOKEN)
dp = Dispatcher()

class Form(StatesGroup):
    waiting_new_cell_title = State()
    waiting_for_data = State()

def split_text(text: str, limit: int = MAX_MSG_LEN):
    if len(text) <= limit:
        return [text]
    return [text[i:i + limit] for i in range(0, len(text), limit)]

def init_db():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ozbekiston_eng_yangi_tarixi_1 TEXT,
            ozbekiston_eng_yangi_tarixi_2 TEXT,
            ozbekiston_eng_yangi_tarixi_3 TEXT,
            ozbekiston_eng_yangi_tarixi_4 TEXT,
            dinshunoslik_1 TEXT,
            dinshunoslik_2 TEXT,
            dinshunoslik_3 TEXT,
            dinshunoslik_4 TEXT,
            falsafa_1 TEXT,
            falsafa_2 TEXT,
            falsafa_3 TEXT,
            falsafa_4 TEXT,
            pedagogik_interfaol_metodlar TEXT,
            ozbekiston_tarixi_adabiyotlar TEXT,
            falsafa_adabiyotlar TEXT,
            dinshunoslik_adabiyotlar TEXT,
            ijodkor_talabalar TEXT,
            qoshimcha_adabiyotlar TEXT,
            izohli_lugat TEXT,
            video_darslar TEXT,
            namunaviy_darslar TEXT,
            lohiya_muallifi TEXT,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("SELECT COUNT(*) FROM materials")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO materials DEFAULT VALUES")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS custom_cells (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content_type TEXT DEFAULT 'empty',
            text_content TEXT,
            file_id TEXT,
            file_name TEXT
        )
    """)
    conn.commit()
    conn.close()

# Asosiy menyu tugmalari va ularning bazadagi nomlari
COLUMNS = {
    "🇺🇿 O'zbekiston tarixi": "ozbekiston_eng_yangi_tarixi",
    "🕌 Dinshunoslik": "dinshunoslik",
    "🧠 Falsafa": "falsafa",
    "📊 Pedagogik metodlar": "pedagogik_interfaol_metodlar",
    "📚 O'zbekiston tarixi adabiyotlar": "ozbekiston_tarixi_adabiyotlar",
    "📖 Falsafa adabiyotlar": "falsafa_adabiyotlar",
    "📘 Dinshunoslik adabiyotlar": "dinshunoslik_adabiyotlar",
    "✍️ Ijodkor talabalar": "ijodkor_talabalar",
    "📁 Qo'shimcha adabiyotlar": "qoshimcha_adabiyotlar",
    "🔍 Izohli lug'at": "izohli_lugat",
    "🎬 Video darslar": "video_darslar",
    "📋 Namunaviy darslar": "namunaviy_darslar",
    "👨‍💻 Loyiha muallifi": "lohiya_muallifi",
}

SUB_SUBJECTS_DB = ["ozbekiston_eng_yangi_tarixi", "dinshunoslik", "falsafa"]

def get_custom_cells():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, content_type, text_content, file_id, file_name FROM custom_cells ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()
    return rows

def build_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    keys = list(COLUMNS.keys())
    keyboard_buttons = []
    for i in range(0, len(keys), 2):
        row = [KeyboardButton(text=keys[i])]
        if i + 1 < len(keys):
            row.append(KeyboardButton(text=keys[i+1]))
        keyboard_buttons.append(row)

    custom_rows = get_custom_cells()
    if custom_rows:
        keyboard_buttons.append([KeyboardButton(text="🗂 Qo'shimcha yacheykalar")])

    if user_id in ADMIN_IDS:
        keyboard_buttons.append([
            KeyboardButton(text="➕ Yangi yacheyka qo'shish"),
            KeyboardButton(text="✏️ Ma'lumot qo'shish/o'zgartirish")
        ])

    return ReplyKeyboardMarkup(
        keyboard=keyboard_buttons,
        resize_keyboard=True
    )

@dp.message(Command("start"))
async def start_handler(message: Message, state: FSMContext):
    await state.clear()
    markup = build_main_keyboard(message.from_user.id)

    if os.path.exists(LOGO_PATH):
        await message.answer_photo(
            photo=FSInputFile(LOGO_PATH),
            caption=WELCOME_TEXT,
            reply_markup=markup
        )
    else:
        await message.answer(WELCOME_TEXT, reply_markup=markup)

# --- YANGI YACHEYKA QO'SHISH ---
@dp.message(F.text == "➕ Yangi yacheyka qo'shish")
async def add_new_cell_start(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(Form.waiting_new_cell_title)
    await message.answer(
        "🆕 Yangi yacheyka nomini kiriting (masalan: <i>1-mavzu taqdimot</i> yoki <i>Kitoblar</i>):",
        parse_mode="HTML"
    )

@dp.message(Form.waiting_new_cell_title)
async def save_new_cell_title(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    title = (message.text or "").strip()
    if not title:
        await message.answer("⚠️ Yacheyka nomi bo'sh bo'lmasligi kerak. Qaytadan kiriting:")
        return

    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO custom_cells (title, content_type) VALUES (?, 'empty')", (title,))
    cell_id = cursor.lastrowid
    conn.commit()
    conn.close()

    await state.update_data(target_type="custom", cell_id=cell_id, title=title)
    await state.set_state(Form.waiting_for_data)

    markup = build_main_keyboard(message.from_user.id)
    safe_title = html.escape(title)
    await message.answer(
        f"✅ <b>{safe_title}</b> yacheykasi yaratildi!\n\n"
        f"Endi shu yacheykaga <b>matn</b> yoki <b>fayl (PowerPoint, kitob/PDF, video, rasm)</b> yuboring:",
        parse_mode="HTML",
        reply_markup=markup
    )

# --- FOYDALANUVCHI UCHUN QO'SHIMCHA YACHEYKALAR ---
@dp.message(F.text == "🗂 Qo'shimcha yacheykalar")
async def show_custom_cells_menu(message: Message):
    rows = get_custom_cells()
    if not rows:
        await message.answer("⚠️ Hozircha qo'shimcha yacheykalar yo'q.")
        return

    buttons = [
        [InlineKeyboardButton(text=f"📌 {title}", callback_data=f"open_custom_{cell_id}")]
        for cell_id, title, *_ in rows
    ]
    await message.answer("🗂 Kerakli yacheykani tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("open_custom_"))
async def open_custom_cell(callback: CallbackQuery):
    cell_id = int(callback.data.replace("open_custom_", ""))
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, content_type, text_content, file_id, file_name FROM custom_cells WHERE id = ?", (cell_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        await callback.answer("Bu yacheyka o'chirilgan.", show_alert=True)
        return

    _, title, content_type, text_content, file_id, _ = row
    safe_title = html.escape(title)
    safe_text = html.escape(text_content) if text_content else ""

    admin_controls = []
    if callback.from_user.id in ADMIN_IDS:
        admin_controls.append([
            InlineKeyboardButton(text="✏️ Tahrirlash", callback_data=f"edit_custom_{cell_id}"),
            InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"del_custom_{cell_id}")
        ])
    reply_markup = InlineKeyboardMarkup(inline_keyboard=admin_controls) if admin_controls else None

    if content_type == "document" and file_id:
        caption = f"📎 <b>{safe_title}</b>" + (f"\n\n{safe_text}" if safe_text else "")
        await callback.message.answer_document(document=file_id, caption=caption[:1024], parse_mode="HTML", reply_markup=reply_markup)
    elif content_type == "video" and file_id:
        caption = f"🎬 <b>{safe_title}</b>" + (f"\n\n{safe_text}" if safe_text else "")
        await callback.message.answer_video(video=file_id, caption=caption[:1024], parse_mode="HTML", reply_markup=reply_markup)
    elif content_type == "photo" and file_id:
        caption = f"🖼 <b>{safe_title}</b>" + (f"\n\n{safe_text}" if safe_text else "")
        await callback.message.answer_photo(photo=file_id, caption=caption[:1024], parse_mode="HTML", reply_markup=reply_markup)
    elif content_type == "audio" and file_id:
        caption = f"🎵 <b>{safe_title}</b>" + (f"\n\n{safe_text}" if safe_text else "")
        await callback.message.answer_audio(audio=file_id, caption=caption[:1024], parse_mode="HTML", reply_markup=reply_markup)
    elif text_content:
        full_msg = f"📖 <b>{safe_title}</b>:\n\n{safe_text}"
        for part in split_text(full_msg):
            await callback.message.answer(part, parse_mode="HTML", reply_markup=reply_markup)
    else:
        await callback.message.answer(f"⚠️ <b>{safe_title}</b> yacheykasida hali ma'lumot yo'q.", parse_mode="HTML", reply_markup=reply_markup)

    await callback.answer()

# --- ADMIN PANEL (TAHRIRLASH VA O'CHIRISH) ---
@dp.message(F.text == "✏️ Ma'lumot qo'shish/o'zgartirish")
async def admin_panel(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    buttons = [
        [InlineKeyboardButton(text=f"Tahrirlash: {title}", callback_data=f"edit_main_{db_col}")]
        for title, db_col in COLUMNS.items()
    ]

    for cell_id, title, *_ in get_custom_cells():
        buttons.append([
            InlineKeyboardButton(text=f"✏️ {title}", callback_data=f"edit_custom_{cell_id}"),
            InlineKeyboardButton(text="🗑", callback_data=f"del_custom_{cell_id}")
        ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Qaysi bo'lim yoki yacheykani tahrirlaysiz yoki o'chirasiz?", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("edit_custom_"))
async def edit_custom_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    cell_id = int(callback.data.replace("edit_custom_", ""))
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT title FROM custom_cells WHERE id = ?", (cell_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        await callback.answer("Yacheyka topilmadi.", show_alert=True)
        return

    title = row[0]
    await state.update_data(target_type="custom", cell_id=cell_id, title=title)
    await state.set_state(Form.waiting_for_data)
    await callback.message.answer(
        f"✍️ <b>{html.escape(title)}</b> uchun yangi <b>matn</b> yoki <b>fayl (PowerPoint, kitob, video, rasm)</b> yuboring:",
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("del_custom_"))
async def delete_custom_cell(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    cell_id = int(callback.data.replace("del_custom_", ""))
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT title FROM custom_cells WHERE id = ?", (cell_id,))
    row = cursor.fetchone()
    if row:
        cursor.execute("DELETE FROM custom_cells WHERE id = ?", (cell_id,))
        conn.commit()
    conn.close()

    await callback.message.answer(f"🗑 <b>{html.escape(row[0] if row else 'Yacheyka')}</b> o'chirildi.", parse_mode="HTML")
    await callback.answer("O'chirildi")

@dp.callback_query(F.data.startswith("edit_main_"))
async def edit_main_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return

    db_col = callback.data.replace("edit_main_", "")

    if db_col in SUB_SUBJECTS_DB:
        buttons = [
            [InlineKeyboardButton(text="1-bosqich", callback_data=f"edit_sub_{db_col}_1")],
            [InlineKeyboardButton(text="2-bosqich", callback_data=f"edit_sub_{db_col}_2")],
            [InlineKeyboardButton(text="3-bosqich", callback_data=f"edit_sub_{db_col}_3")],
            [InlineKeyboardButton(text="4-bosqich", callback_data=f"edit_sub_{db_col}_4")],
        ]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text("Qaysi bosqich uchun ma'lumot kiritasiz?", reply_markup=keyboard)
    else:
        title = next((k for k, v in COLUMNS.items() if v == db_col), db_col)
        await state.update_data(target_type="main", target_column=db_col, title=title)
        await state.set_state(Form.waiting_for_data)
        await callback.message.delete()
        await callback.message.answer(f"✍️ <b>{html.escape(title)}</b> uchun yangi ma'lumotni yuboring:", parse_mode="HTML")

    await callback.answer()

@dp.callback_query(F.data.startswith("edit_sub_"))
async def edit_sub_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return

    data_parts = callback.data.replace("edit_sub_", "").rsplit("_", 1)
    db_col = data_parts[0]
    course = data_parts[1]

    target_column = f"{db_col}_{course}"
    base_title = next((k for k, v in COLUMNS.items() if v == db_col), db_col)
    title = f"{base_title} ({course}-bosqich)"

    await state.update_data(target_type="main", target_column=target_column, title=title)
    await state.set_state(Form.waiting_for_data)

    await callback.message.delete()
    await callback.message.answer(f"✍️ <b>{html.escape(title)}</b> uchun yangi ma'lumotni yuboring:", parse_mode="HTML")
    await callback.answer()

# --- MA'LUMOT VA FAYLLARNI SAQLASH ---
@dp.message(Form.waiting_for_data)
async def save_user_input(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    user_data = await state.get_data()
    target_type = user_data.get("target_type", "main")
    title = user_data.get("title", "Bo'lim")
    safe_title = html.escape(title)

    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()

    if target_type == "custom":
        cell_id = user_data.get("cell_id")
        caption_or_text = message.caption or message.text or ""

        if message.document:
            cursor.execute(
                "UPDATE custom_cells SET content_type='document', text_content=?, file_id=?, file_name=? WHERE id=?",
                (caption_or_text, message.document.file_id, message.document.file_name, cell_id)
            )
            saved_desc = f"fayl ({html.escape(message.document.file_name or 'hujjat')})"
        elif message.video:
            cursor.execute(
                "UPDATE custom_cells SET content_type='video', text_content=?, file_id=?, file_name=? WHERE id=?",
                (caption_or_text, message.video.file_id, message.video.file_name or "video.mp4", cell_id)
            )
            saved_desc = "video"
        elif message.photo:
            photo = message.photo[-1]
            cursor.execute(
                "UPDATE custom_cells SET content_type='photo', text_content=?, file_id=?, file_name=? WHERE id=?",
                (caption_or_text, photo.file_id, "photo.jpg", cell_id)
            )
            saved_desc = "rasm"
        elif message.audio:
            cursor.execute(
                "UPDATE custom_cells SET content_type='audio', text_content=?, file_id=?, file_name=? WHERE id=?",
                (caption_or_text, message.audio.file_id, message.audio.file_name or "audio.mp3", cell_id)
            )
            saved_desc = "audio"
        elif message.text:
            cursor.execute(
                "UPDATE custom_cells SET content_type='text', text_content=?, file_id=NULL, file_name=NULL WHERE id=?",
                (message.text, cell_id)
            )
            saved_desc = "matn"
        else:
            conn.close()
            await message.answer("⚠️ Ushbu format qo'llab-quvvatlanmaydi. Matn, hujjat/kitob/taqdimot, video, rasm yoki audio yuboring.")
            return

        conn.commit()
        conn.close()
        await state.clear()
        await message.answer(f"✅ <b>{safe_title}</b> yacheykasiga {saved_desc} saqlandi!", parse_mode="HTML")
        return

    target_column = user_data.get("target_column")
    if message.document:
        text_to_save = f"{message.caption or ''} [Fayl: {message.document.file_name or 'hujjat'}]".strip()
    elif message.video:
        text_to_save = f"{message.caption or ''} [Video fayl]".strip()
    else:
        text_to_save = message.text or message.caption or ""

    cursor.execute(f"UPDATE materials SET {target_column} = ? WHERE id = 1", (text_to_save,))
    conn.commit()
    conn.close()

    await state.clear()
    await message.answer(f"✅ <b>{safe_title}</b> bo'limiga ma'lumot muvaffaqiyatli saqlandi!", parse_mode="HTML")

# --- ASOSIY BO'LIMLARNI KO'RSATISH ---
@dp.message(F.text.in_(COLUMNS.keys()))
async def show_material(message: Message):
    title = message.text
    db_column = COLUMNS[title]
    safe_title = html.escape(title)

    if db_column in SUB_SUBJECTS_DB:
        buttons = [
            [InlineKeyboardButton(text="1-bosqich", callback_data=f"show_{db_column}_1")],
            [InlineKeyboardButton(text="2-bosqich", callback_data=f"show_{db_column}_2")],
            [InlineKeyboardButton(text="3-bosqich", callback_data=f"show_{db_column}_3")],
            [InlineKeyboardButton(text="4-bosqich", callback_data=f"show_{db_column}_4")],
        ]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer(f"🎓 <b>{safe_title}</b> bo'yicha kerakli bosqichni tanlang:", parse_mode="HTML", reply_markup=keyboard)
    else:
        conn = sqlite3.connect("bot_database.db")
        cursor = conn.cursor()
        cursor.execute(f"SELECT {db_column} FROM materials WHERE id = 1")
        row = cursor.fetchone()
        conn.close()

        content = row[0] if row and row[0] else "⚠️ Bu bo'limga hali ma'lumot kiritilmagan."
        full_msg = f"📖 <b>{safe_title}</b>:\n\n{html.escape(content)}"
        for part in split_text(full_msg):
            await message.answer(part, parse_mode="HTML")

@dp.callback_query(F.data.startswith("show_"))
async def show_course_material(callback: CallbackQuery):
    data_parts = callback.data.replace("show_", "").rsplit("_", 1)
    db_col = data_parts[0]
    course = data_parts[1]

    target_column = f"{db_col}_{course}"
    base_title = next((k for k, v in COLUMNS.items() if v == db_col), db_col)
    title = f"{base_title} ({course}-bosqich)"
    safe_title = html.escape(title)

    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute(f"SELECT {target_column} FROM materials WHERE id = 1")
    row = cursor.fetchone()
    conn.close()

    content = row[0] if row and row[0] else "⚠️ Bu bosqichga hali ma'lumot kiritilmagan."
    full_msg = f"📖 <b>{safe_title}</b>:\n\n{html.escape(content)}"
    for part in split_text(full_msg):
        await callback.message.answer(part, parse_mode="HTML")
    await callback.answer()

async def main():
    init_db()
    print("Bot ishga tushdi...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    keep_alive()
    asyncio.run(main())