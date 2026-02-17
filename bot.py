from datetime import datetime, timedelta
import os
import psycopg2

from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup

# ================== CONFIG ==================
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 6214795350

bot = Bot(token=TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

# ================== DATABASE (PostgreSQL) ==================
DATABASE_URL = os.getenv("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()

# --- таблица users ---
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    phone TEXT,
    name TEXT,
    lang TEXT,
    status TEXT,
    bonus INTEGER DEFAULT 0,
    bonus_total INTEGER DEFAULT 0,
    purchases INTEGER DEFAULT 0,
    bonus_expire TIMESTAMP,
    expire_notified INTEGER DEFAULT 0,
    bonus_expired INTEGER DEFAULT 0
)
""")

# --- таблица operations ---
cursor.execute("""
CREATE TABLE IF NOT EXISTS operations (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    type TEXT,
    purchase_sum INTEGER,
    bonus_amount INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

conn.commit()

# ================== HELPERS ==================

def get_user(uid):
    cursor.execute("SELECT * FROM users WHERE user_id=%s", (uid,))
    return cursor.fetchone()


def fmt_date(date_val):
    if not date_val:
        return "—"

    # PostgreSQL возвращает datetime
    if isinstance(date_val, datetime):
        return date_val.strftime("%d.%m.%Y")

    # если вдруг строка
    return datetime.strptime(str(date_val), "%Y-%m-%d").strftime("%d.%m.%Y")


def calc_status(purchases):
    if purchases >= 15:
        return "Vip (вип ухти)"
    if purchases >= 5:
        return "Своя (постоянная ухти)"
    return "Гостья (новая ухти)"


def calc_percent(status):
    if status.startswith("Vip"):
        return 0.02
    if status.startswith("Своя"):
        return 0.015
    return 0.01


def fmt_money(x: int) -> str:
    return f"{x:,}".replace(",", " ")


def fmt_datetime(dt_val):
    if not dt_val:
        return "—"

    if isinstance(dt_val, datetime):
        return dt_val.strftime("%d.%m.%Y")

    return datetime.strptime(str(dt_val), "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y")


# --- уведомление за 10 дней ---
async def check_bonus_expire(uid):
    u = get_user(uid)
    if not u:
        return

    bonus_expire = u[8]       # TIMESTAMP
    notified = u[9]

    if not bonus_expire or notified == 1:
        return

    # PostgreSQL уже отдаёт datetime
    expire_date = bonus_expire if isinstance(bonus_expire, datetime) \
        else datetime.strptime(str(bonus_expire), "%Y-%m-%d")

    days_left = (expire_date - datetime.now()).days

    if days_left == 10:
        text_ru = (
            "❕Напоминаем:\n\n"
            "До окончания срока действия ваших бонусов осталось 10 дней.\n"
            "Вы можете использовать их при следующей покупке 🤍"
        )
        text_uz = (
            "❕Eslatma:\n\n"
            "Bonuslaringiz amal qilish muddati tugashiga 10 kun qoldi.\n"
            "Ularni keyingi xaridda ishlatishingiz mumkin 🤍"
        )

        await bot.send_message(uid, text_ru if u[3] == "ru" else text_uz)

        cursor.execute(
            "UPDATE users SET expire_notified = 1 WHERE user_id=%s",
            (uid,)
        )
        conn.commit()

# --- автосгорание бонусов ---
async def expire_bonuses_if_needed(uid):
    u = get_user(uid)
    if not u:
        return

    bonus_expire = u[8]   # TIMESTAMP
    expired = u[10]

    if not bonus_expire or expired == 1:
        return

    # PostgreSQL возвращает datetime
    expire_date = bonus_expire if isinstance(bonus_expire, datetime) \
        else datetime.strptime(str(bonus_expire), "%Y-%m-%d")

    if datetime.now() >= expire_date:
        cursor.execute("""
            UPDATE users
            SET bonus = 0,
                bonus_expired = 1
            WHERE user_id = %s
        """, (uid,))
        conn.commit()

        text_ru = (
            "Срок действия ваших бонусов завершился :(\n\n"
            "Мы будем рады начислить вам новые бонусы при следующей покупке ✨"
        )
        text_uz = (
            "Bonuslaringiz amal qilish muddati yakunlandi :(\n\n"
            "Keyingi xaridlarda sizga yangi bonuslar berishdan mamnun bo‘lamiz ✨"
        )

        await bot.send_message(uid, text_ru if u[3] == "ru" else text_uz)

# ================== KEYBOARDS ==================
def lang_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🇷🇺 Русский", "🇺🇿 O‘zbekcha")
    return kb

def phone_kb(lang):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton(
        "📱 Отправить номер" if lang == "ru" else "📱 Raqamni yuborish",
        request_contact=True
    ))
    return kb

def menu(lang):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    if lang == "ru":
        kb.add("💳 Моя карта")
        kb.add("💰 Мои бонусы")
        kb.add("🛍 История покупок")
        kb.add("📞 Связаться с нами")
    else:
        kb.add("💳 Mening kartam")
        kb.add("💰 Mening bonuslarim")
        kb.add("🛍 Xaridlar tarixi")
        kb.add("📞 Bog‘lanish")
    return kb

def back_kb(lang):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("⬅️ Назад" if lang == "ru" else "⬅️ Orqaga")
    return kb

def admin_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("➕ Начислить бонусы", "➖ Списать бонусы")
    kb.add("📊 Статистика", "🏆 Топ клиент")
    kb.add("🔍 Найти клиента","📤 Выгрузка клиентов (Excel)")  
    kb.add("⬅️ Назад")
    return kb

# ================== STATES ==================
class Reg(StatesGroup):
    phone = State()
    name = State()

class Review(StatesGroup):
    text = State()

class AdminAdd(StatesGroup):
    phone = State()
    amount = State()

class AdminMinus(StatesGroup):
    phone = State()
    amount = State()

class AdminFind(StatesGroup):
    phone = State()


# ================== START ==================
@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    user = get_user(message.from_user.id)

    if user:
        # проверка напоминания за 10 дней
        await check_bonus_expire(message.from_user.id)
        # автосгорание бонусов
        await expire_bonuses_if_needed(message.from_user.id)

        await message.answer(
            "Рады снова видеть вас 🫂" if user[3] == "ru" else "Sizni yana ko‘rganimizdan xursandmiz 🫂",
            reply_markup=menu(user[3])
        )
    else:
        await message.answer(
            "Ассаламу алейкум уа рохматуллахи уа барокатух, давайте для начала выберем язык обслуживания☺️\n\n"
            "Assalomu aleykum va rohmatullahi va barokatuh, keling, avvaliga xizmat ko’rsatish tilini tanlab olaylik☺️",
            reply_markup=lang_kb()
        )


# ================== LANGUAGE ==================
@dp.message_handler(lambda m: m.text in ["🇷🇺 Русский", "🇺🇿 O‘zbekcha"])
async def choose_lang(message: types.Message):
    lang = "ru" if "Русский" in message.text else "uz"
    uid = message.from_user.id

    cursor.execute("""
        INSERT INTO users (user_id, lang, status)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id)
        DO UPDATE SET
            lang = EXCLUDED.lang,
            status = EXCLUDED.status
    """, (uid, lang, "Гостья (новая ухти)"))

    conn.commit()

    await Reg.phone.set()
    await message.answer(
        "Добро пожаловать в нашу программу лояльности 🫂\n\n"
        "Отправьте номер телефона, чтобы накапливать бонусы с каждой покупки 🛍"
        if lang == "ru" else
        "Bonus dasturimizga xush kelibsiz 🫂\n\n"
        "Bonuslar yig‘ish uchun telefon raqamingizni yuboring 🛍",
        reply_markup=phone_kb(lang)
    )

# ================== PHONE ==================
@dp.message_handler(content_types=types.ContentType.CONTACT, state=Reg.phone)
async def get_phone(message: types.Message, state: FSMContext):
    uid = message.from_user.id

    cursor.execute(
        "UPDATE users SET phone=%s WHERE user_id=%s",
        (message.contact.phone_number, uid)
    )
    conn.commit()

    user = get_user(uid)
    lang = user[3] if user else "ru"

    await Reg.name.set()
    await message.answer(
        "Спасибо! 🤍\nНапишите, пожалуйста, ваше имя:"
        if lang == "ru" else
        "Rahmat! 🤍\nIltimos, ismingizni yozing:",
        reply_markup=types.ReplyKeyboardRemove()
    )


# ================== NAME ==================
@dp.message_handler(state=Reg.name)
async def get_name(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    name = message.text.strip()

    cursor.execute(
        "UPDATE users SET name=%s WHERE user_id=%s",
        (name, uid)
    )
    conn.commit()

    await state.finish()

    user = get_user(uid)
    lang = user[3] if user else "ru"

    await message.answer(
        f"Рады видеть вас, {name} 💫\n\n"
        "В этом боте вы можете отслеживать свои бонусы и покупки.\n\n"
        "🌟 С каждой покупки вам начисляются бонусы, их можно копить и использовать при следующих заказах\n"
        "⏳ Бонусы действуют 12 месяцев с момента первого начисления\n\n"
        "Выберите пункт меню ниже ⬇️"
        if lang == "ru" else
        f"Sizni ko‘rib turganimizdan xursandmiz, {name} 💫\n\n"
        "Bu bot orqali siz bonuslaringiz va xaridlaringizni kuzatib borishingiz mumkin.\n\n"
        "🌟 Har bir xariddan sizga bonuslar beriladi, ularni jamlab, keyingi buyurtmalarda ishlatishingiz mumkin\n"
        "⏳ Bonuslar birinchi hisoblangan kundan boshlab 12 oy amal qiladi\n\n"
        "Quyidagi menyudan kerakli bo‘limni tanlang ⬇️",
        reply_markup=menu(lang)
    )

# ================== CLIENT MENU ==================
@dp.message_handler(lambda m: m.text in ["💳 Моя карта", "💳 Mening kartam"])
async def my_card(message: types.Message):
    u = get_user(message.from_user.id)

    if not u:
        await message.answer("Пожалуйста, сначала зарегистрируйтесь 🙏")
        return

    lang = u[3]

    await message.answer(
        f"💳 Моя карта\n\n"
        f"👤 Имя: {u[2] or '—'}\n"
        f"📱 Телефон: {u[1] or '—'}\n"
        f"🆔 ID: {u[0]}\n"
        f"⭐️ Статус: {u[4]}\n\n"
        f"📌 Сообщите номер телефона при покупке"
        if lang == "ru" else
        f"💳 Mening kartam\n\n"
        f"👤 Ism: {u[2] or '—'}\n"
        f"📱 Telefon: {u[1] or '—'}\n"
        f"🆔 ID: {u[0]}\n"
        f"⭐️ Daraja: {u[4]}\n\n"
        f"📌 Xarid paytida telefon raqamingizni ayting",
        reply_markup=menu(lang)
    )


@dp.message_handler(lambda m: m.text in ["💰 Мои бонусы", "💰 Mening bonuslarim"])
async def bonuses(message: types.Message):
    uid = message.from_user.id

    await check_bonus_expire(uid)
    await expire_bonuses_if_needed(uid)

    u = get_user(uid)

    if not u:
        await message.answer("Пожалуйста, сначала зарегистрируйтесь 🙏")
        return

    lang = u[3]

    await message.answer(
        f"💰 Текущий бонусный баланс: {fmt_money(u[5] or 0)} сум\n"
        f"🌟 Заработано за все время: {fmt_money(u[6] or 0)} сум\n\n"
        f"⏳ Бонусы действуют до: {fmt_date(u[8])}"
        if lang == "ru" else
        f"💰 Joriy bonus balans: {fmt_money(u[5] or 0)} so‘m\n"
        f"🌟 Umumiy yig‘ilgan: {fmt_money(u[6] or 0)} so‘m\n\n"
        f"⏳ Bonuslar amal qilish muddati: {fmt_date(u[8])}",
        reply_markup=menu(lang)
    )

# ---------- формат денег с пробелами ----------
def fmt_money(amount):
    return "{:,}".format(amount or 0).replace(",", " ")


@dp.message_handler(lambda m: m.text in ["🛍 История покупок", "🛍 Xaridlar tarixi"])
async def history(message: types.Message):
    uid = message.from_user.id
    u = get_user(uid)

    if not u:
        await message.answer("Пожалуйста, сначала зарегистрируйтесь 🙏")
        return

    lang = u[3]

    cursor.execute("""
        SELECT type, purchase_sum, bonus_amount, created_at
        FROM operations
        WHERE user_id = %s
        ORDER BY created_at DESC
        LIMIT 10
    """, (uid,))
    rows = cursor.fetchall()

    if not rows:
        await message.answer(
            "У вас пока нет покупок :(\nБонусы начнут копиться после первой покупки 🛍"
            if lang == "ru" else
            "Sizda hali xaridlar yo‘q :(\nBonuslar birinchi xariddan keyin yig‘ila boshlaydi 🛍",
            reply_markup=menu(lang)
        )
        return

    if lang == "ru":
        text = "🛍 История покупок:\n\n"
        for t, p, b, d in rows:

            if isinstance(d, datetime):
                date = d.strftime("%d.%m.%Y")
            else:
                date = datetime.strptime(str(d), "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y")

            if t == "add":
                text += (
                    f"📅 {date}\n"
                    f"➕ Начисление\n"
                    f"💸 Покупка: {fmt_money(p)} сум\n"
                    f"💰 Бонусы: +{fmt_money(b)} сум\n\n"
                )
            else:
                text += (
                    f"📅 {date}\n"
                    f"➖ Списание бонусов\n"
                    f"💰 −{fmt_money(b)} сум\n\n"
                )
    else:
        text = "🛍 Xaridlar tarixi:\n\n"
        for t, p, b, d in rows:

            if isinstance(d, datetime):
                date = d.strftime("%Y-%m-%d")
            else:
                date = str(d)[:10]

            if t == "add":
                text += (
                    f"📅 {date}\n"
                    f"➕ Bonus hisoblandi\n"
                    f"💸 Xarid: {fmt_money(p)} so‘m\n"
                    f"💰 +{fmt_money(b)} so‘m\n\n"
                )
            else:
                text += (
                    f"📅 {date}\n"
                    f"➖ Bonus yechildi\n"
                    f"💰 −{fmt_money(b)} so‘m\n\n"
                )

    await message.answer(text, reply_markup=menu(lang))


@dp.message_handler(lambda m: m.text in [
    "📞 Связаться с нами",
    "📞 Bog‘lanish"
])
async def contacts(message: types.Message):
    user = get_user(message.from_user.id)

    if not user:
        await message.answer(
            "Пожалуйста, сначала зарегистрируйтесь 🙏\n\n"
            "Iltimos, avval ro‘yxatdan o‘ting 🙏",
            reply_markup=lang_kb()
        )
        return

    lang = user[3]

    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton(
            "📩 Telegram",
            url="https://t.me/tymapucclo"
        ),
        types.InlineKeyboardButton(
            "💌 Instagram",
            url="https://instagram.com/tymapuc.clo"
        )
    )

    await message.answer(
        "Выберите удобный способ для связи:"
        if lang == "ru"
        else "Biz bilan bog‘lanish uchun qulay usulni tanlang:",
        reply_markup=kb
    )

# ================== REVIEW / BACK ==================

@dp.message_handler(lambda m: m.text in ["⬅️ Назад", "⬅️ Orqaga"], state="*")
async def back_any(message: types.Message, state: FSMContext):
    await state.finish()

    uid = message.from_user.id

    # 🔐 если админ — возвращаем в админ-панель
    if uid == ADMIN_ID:
        await message.answer(
            "🔐 Админ-панель",
            reply_markup=admin_menu()
        )
        return

    # 👤 обычный пользователь
    user = get_user(uid)

    # ❌ если пользователь ещё не зарегистрирован
    if not user:
        await message.answer(
            "Пожалуйста, сначала зарегистрируйтесь :)\n\n"
            "Iltimos, avval ro‘yxatdan o‘ting :)",
            reply_markup=lang_kb()
        )
        return

    # ✅ зарегистрированный клиент
    lang = user[3] if user else "ru"

    await message.answer(
        "Выберите пункт меню ниже ⬇️"
        if lang == "ru"
        else "Quyidagi menyudan kerakli bo‘limni tanlang ⬇️",
        reply_markup=menu(lang)
    )


# ================== ADMIN ==================
@dp.message_handler(commands=["admin"])
async def admin_start(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("🔐 Админ-панель", reply_markup=admin_menu())


# -------- ADD BONUS --------
@dp.message_handler(lambda m: m.text == "➕ Начислить бонусы")
async def add_start(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await AdminAdd.phone.set()
    await message.answer("Введите номер телефона клиента:")


@dp.message_handler(state=AdminAdd.phone)
async def add_phone(message: types.Message, state: FSMContext):
    cursor.execute("SELECT user_id FROM users WHERE phone=%s", (message.text,))
    user = cursor.fetchone()

    if not user:
        await state.finish()
        await message.answer("❌ Клиент не найден", reply_markup=admin_menu())
        return

    await state.update_data(uid=user[0])
    await AdminAdd.amount.set()
    await message.answer("Введите сумму покупки:")


@dp.message_handler(state=AdminAdd.amount)
async def add_amount(message: types.Message, state: FSMContext):
    data = await state.get_data()
    uid = data["uid"]

    try:
        purchase = int(message.text)
    except:
        await message.answer("Введите сумму цифрами:")
        return

    # текущие данные пользователя
    u = get_user(uid)
    old_status = u[4]
    lang = u[3]

    # +1 покупка
    new_purchases = u[7] + 1

    # новый статус
    new_status = calc_status(new_purchases)

    # процент по статусу
    percent = calc_percent(new_status)
    начислено = int(purchase * percent)

    # срок действия бонусов — 365 дней
    expire = (datetime.now() + timedelta(days=365))

    # обновляем пользователя
    cursor.execute("""
        UPDATE users SET
            purchases = %s,
            status = %s,
            bonus = bonus + %s,
            bonus_total = bonus_total + %s,
            bonus_expire = %s
        WHERE user_id = %s
    """, (
        new_purchases,
        new_status,
        начислено,
        начислено,
        expire,
        uid
    ))
    conn.commit()

    # --- запись операции начисления ---
    cursor.execute("""
        INSERT INTO operations (
            user_id,
            type,
            purchase_sum,
            bonus_amount,
            created_at
        )
        VALUES (%s, %s, %s, %s, NOW())
    """, (
        uid,
        "add",
        purchase,
        начислено
    ))
    conn.commit()

    # 🔔 проверка срока бонусов (за 10 дней)
    await check_bonus_expire(uid)

    # -------- сообщение о начислении --------
    text_ru = (
        "Спасибо за ваш выбор!)\n\n"
        f"💸 Сумма покупки: {fmt_money(purchase)} сум\n"
        f"💰 Начислено бонусов: {fmt_money(начислено)} сум\n\n"
        "Ваш статус растёт — вместе с ним растут и бонусы ❤️‍🔥"
    )

    text_uz = (
        "Tanlovingiz uchun rahmat!)\n\n"
        f"💸 Xarid summasi: {fmt_money(purchase)} so‘m\n"
        f"💰 Hisoblangan bonuslar: {fmt_money(начислено)} so‘m\n\n"
        "Darajangiz oshib bormoqda — bonuslar ham ko‘paymoqda ❤️‍🔥"
    )

    await bot.send_message(uid, text_ru if lang == "ru" else text_uz)

    # -------- уведомление о смене статуса --------
    if new_status != old_status:
        if lang == "ru":
            if old_status.startswith("Гостья") and new_status.startswith("Своя"):
                notify_text = (
                    "Поздравляем!\n\n"
                    "Ваш статус обновился → Своя (постоянная ухти) 🤍\n"
                    "Теперь вам начисляется больше бонусов с каждой покупки 💫"
                )
            elif old_status.startswith("Своя") and new_status.startswith("Vip"):
                notify_text = (
                    "Поздравляем!\n\n"
                    "Вы достигли статуса Vip (вип ухти) ❤️‍🔥\n"
                    "Теперь вы получаете максимальный процент бонусов с каждой покупки 🔥"
                )
            else:
                notify_text = None
        else:
            if old_status.startswith("Гостья") and new_status.startswith("Своя"):
                notify_text = (
                    "Tabriklaymiz!\n\n"
                    "Darajangiz yangilandi → Своя (постоянная ухти) 🤍\n"
                    "Endi har bir xariddan ko‘proq bonuslar olasiz 💫"
                )
            elif old_status.startswith("Своя") and new_status.startswith("Vip"):
                notify_text = (
                    "Tabriklaymiz!\n\n"
                    "Siz Vip (вип ухти) darajasiga yetdingiz ❤️‍🔥\n"
                    "Endi sizga maksimal bonuslar beriladi 🔥"
                )
            else:
                notify_text = None

        if notify_text:
            await bot.send_message(uid, notify_text)

    await state.finish()
    await message.answer("✅ Бонусы начислены", reply_markup=admin_menu())


# -------- MINUS BONUS --------
@dp.message_handler(lambda m: m.text == "➖ Списать бонусы")
async def minus_start(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await AdminMinus.phone.set()
    await message.answer("Введите номер телефона клиента:")


@dp.message_handler(state=AdminMinus.phone)
async def minus_phone(message: types.Message, state: FSMContext):
    cursor.execute(
        "SELECT user_id, bonus, lang FROM users WHERE phone=%s",
        (message.text,)
    )
    user = cursor.fetchone()

    if not user:
        await state.finish()
        await message.answer("❌ Клиент не найден", reply_markup=admin_menu())
        return

    await state.update_data(uid=user[0], bonus=user[1], lang=user[2])
    await AdminMinus.amount.set()
    await message.answer("Введите сумму списания:")


@dp.message_handler(state=AdminMinus.amount)
async def minus_amount(message: types.Message, state: FSMContext):
    data = await state.get_data()

    try:
        amount = int(message.text)
    except:
        await message.answer("Введите сумму цифрами:")
        return

    if amount > data["bonus"]:
        await message.answer("❌ Недостаточно бонусов")
        return

    # списываем бонусы
    cursor.execute(
        "UPDATE users SET bonus = bonus - %s WHERE user_id = %s",
        (amount, data["uid"])
    )

    # записываем операцию (ОДИН РАЗ)
    cursor.execute("""
        INSERT INTO operations (
            user_id,
            type,
            purchase_sum,
            bonus_amount,
            created_at
        )
        VALUES (%s, %s, %s, %s, NOW())
    """, (
        data["uid"],
        "minus",
        0,
        amount
    ))

    conn.commit()

    # сообщение клиенту
    text_ru = (
        f"С ваших бонусов списано: {fmt_money(amount)} сум\n\n"
        "💰 Текущий бонусный баланс обновлён"
    )

    text_uz = (
        f"Bonuslaringizdan {fmt_money(amount)} so‘m yechildi\n\n"
        "💰 Joriy bonus balans yangilandi"
    )

    await bot.send_message(
        data["uid"],
        text_ru if data["lang"] == "ru" else text_uz
    )

    await state.finish()
    await message.answer("✅ Бонусы списаны", reply_markup=admin_menu())

# -------- STATISTICS --------
@dp.message_handler(lambda m: m.text == "📊 Статистика")
async def stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    cursor.execute("SELECT COUNT(*) FROM users")
    users_count = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(purchases) FROM users")
    total_purchases = cursor.fetchone()[0] or 0

    cursor.execute("""
        SELECT SUM(bonus_amount)
        FROM operations
        WHERE type = 'add'
    """)
    added = cursor.fetchone()[0] or 0

    cursor.execute("""
        SELECT SUM(bonus_amount)
        FROM operations
        WHERE type = 'minus'
    """)
    minus = cursor.fetchone()[0] or 0

    text = (
        "📊 Статистика\n\n"
        f"👥 Клиентов всего: {users_count}\n"
        f"🛍 Покупок всего: {total_purchases}\n"
        f"➕ Начислено бонусов: {fmt_money(added)} сум\n"
        f"➖ Списано бонусов: {fmt_money(minus)} сум"
    )

    await message.answer(text, reply_markup=admin_menu())


@dp.message_handler(lambda m: m.text == "🏆 Топ клиент")
async def top_client(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    cursor.execute("""
        SELECT name, phone, user_id, status, purchases, bonus_total
        FROM users
        ORDER BY bonus_total DESC
        LIMIT 1
    """)
    u = cursor.fetchone()

    if not u:
        await message.answer("Нет данных", reply_markup=admin_menu())
        return

    text = (
        "🏆 Топ клиент\n\n"
        f"👤 Имя: {u[0]}\n"
        f"📱 Телефон: {u[1]}\n"
        f"🆔 ID: {u[2]}\n"
        f"⭐️ Статус: {u[3]}\n\n"
        f"Покупок: {u[4]}\n"
        f"Бонусов: {fmt_money(u[5])} сум"
    )

    await message.answer(text, reply_markup=admin_menu())

# -------- FIND CLIENT --------
@dp.message_handler(lambda m: m.text == "🔍 Найти клиента")
async def admin_find_start(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await AdminFind.phone.set()
    await message.answer(
        "Введите номер телефона клиента:",
        reply_markup=types.ReplyKeyboardRemove()
    )


@dp.message_handler(state=AdminFind.phone)
async def admin_find_result(message: types.Message, state: FSMContext):
    phone = message.text.strip()

    cursor.execute("""
        SELECT user_id, name, phone, status, purchases, bonus, bonus_total
        FROM users
        WHERE phone = %s
    """, (phone,))
    u = cursor.fetchone()

    if not u:
        await state.finish()
        await message.answer(
            "❌ Клиент не найден",
            reply_markup=admin_menu()
        )
        return

    text = (
        "👤 Клиент найден\n\n"
        f"👤 Имя: {u[1]}\n"
        f"📱 Телефон: {u[2]}\n"
        f"🆔 ID: {u[0]}\n"
        f"⭐️ Статус: {u[3]}\n\n"
        f"🛍 Покупок: {u[4]}\n"
        f"💰 Бонусы: {fmt_money(u[5])} сум\n"
        f"🌟 Всего начислено: {fmt_money(u[6])} сум"
    )

    await state.finish()
    await message.answer(text, reply_markup=admin_menu())


from openpyxl import Workbook
from openpyxl.styles import Font, Alignment


@dp.message_handler(lambda m: m.text == "📤 Выгрузка клиентов (Excel)")
async def export_clients_excel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    cursor.execute("""
        SELECT
            u.name,
            u.phone,
            u.user_id,
            u.purchases,
            u.bonus_total,
            COALESCE((
                SELECT SUM(o.bonus_amount)
                FROM operations o
                WHERE o.user_id = u.user_id AND o.type = 'minus'
            ), 0) AS bonus_minus,
            u.bonus,
            u.status
        FROM users u
        ORDER BY u.user_id ASC
    """)
    users = cursor.fetchall()

    if not users:
        await message.answer("❌ Нет данных для выгрузки", reply_markup=admin_menu())
        return

    wb = Workbook()
    ws = wb.active
    ws.title = "Клиенты"

    headers = [
        "Имя",
        "Телефон",
        "Telegram ID",
        "Покупок",
        "Начислено бонусов",
        "Списано бонусов",
        "Текущий баланс",
        "Статус"
    ]
    ws.append(headers)

    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center")

    for (
        name,
        phone,
        uid,
        purchases,
        bonus_total,
        bonus_minus,
        bonus,
        status
    ) in users:
        ws.append([
            name or "",
            phone or "",
            str(uid),
            purchases or 0,
            bonus_total or 0,
            bonus_minus or 0,
            bonus or 0,
            status or ""
        ])

    for column_cells in ws.columns:
        max_length = max(
            len(str(cell.value)) if cell.value else 0
            for cell in column_cells
        )
        ws.column_dimensions[column_cells[0].column_letter].width = max_length + 4

    filename = "clients.xlsx"
    wb.save(filename)

    await message.answer_document(
        types.InputFile(filename),
        caption="📊 Полный список клиентов"
    )


# ================== RUN ==================
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)


