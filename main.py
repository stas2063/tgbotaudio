"""
Telegram-бот для сбора донатов для приложения "Голосовой Калькулятор"
Стек: Python 3.10+, aiogram 3.x
Платёжная система: ЮКасса (через Telegram Payments API)
"""

import asyncio
import logging
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    LabeledPrice,
    PreCheckoutQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# ========== КОНФИГУРАЦИЯ ==========
# Замените на свой токен бота (получите у @BotFather)
BOT_TOKEN = "8325211698:AAF_M7lTF3bhJSO2yDtoQany9Cy45XbZzi8"

# Замените на токен провайдера ЮКассы (получите у @BotFather -> Payments)
PAYMENT_PROVIDER_TOKEN = "381764678:TEST:159216"

# Минимальная сумма пожертвования в рублях (лимит Telegram Payments)
MIN_DONATION_AMOUNT = 60

# ========== ТЕКСТЫ СООБЩЕНИЙ (можно редактировать) ==========
WELCOME_MESSAGE = (
    "👋 <b>Привет!</b>\n\n"
    "Я официальный бот <b>Голосового Калькулятора</b>.\n\n"
    "Если приложение тебе помогло, ты можешь поддержать разработку любой суммой.\n\n"
    "Выбери вариант ниже: 👇"
)

ENTER_AMOUNT_MESSAGE = (
    "✏️ Пожалуйста, введи сумму пожертвования числом (в рублях).\n\n"
    f"<i>Минимум {MIN_DONATION_AMOUNT} ₽</i>"
)

INVALID_AMOUNT_MESSAGE = (
    "❌ <b>Некорректная сумма!</b>\n\n"
    f"Пожалуйста, введи целое число не менее {MIN_DONATION_AMOUNT}."
)

THANK_YOU_MESSAGE = (
    "🎉 <b>Огромное спасибо!</b>\n\n"
    "Твоя поддержка очень важна.\n"
    "Благодаря тебе приложение станет еще лучше! ❤️"
)

# GIF для благодарности (можно заменить на свою ссылку)
THANK_YOU_GIF_URL = "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif"

# Описание в инвойсе
INVOICE_TITLE = "Пожертвование"
INVOICE_DESCRIPTION = "Пожертвование на развитие проекта «Голосовой Калькулятор»"

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ========== ИНИЦИАЛИЗАЦИЯ ==========
router = Router()

# Словарь для хранения ID последнего инвойса для каждого пользователя
# {chat_id: message_id}
last_invoice_messages: dict[int, int] = {}

# Словарь для хранения ID сообщения с меню (для удаления после оплаты)
# {chat_id: message_id}
last_menu_messages: dict[int, int] = {}


# ========== СОСТОЯНИЯ FSM ==========
class DonationStates(StatesGroup):
    """Состояния для ввода произвольной суммы"""
    waiting_for_amount = State()


# ========== КЛАВИАТУРА ==========
def get_donation_keyboard() -> InlineKeyboardMarkup:
    """Создаёт inline-клавиатуру с вариантами сумм пожертвования"""
    keyboard = [
        [
            InlineKeyboardButton(text="☕ 150 ₽", callback_data="donate_150"),
            InlineKeyboardButton(text="🚀 300 ₽", callback_data="donate_300"),
        ],
        [
            InlineKeyboardButton(text="💎 500 ₽", callback_data="donate_500"),
            InlineKeyboardButton(text="👑 1000 ₽", callback_data="donate_1000"),
        ],
        [
            InlineKeyboardButton(text="✏️ Ввести свою сумму", callback_data="donate_custom"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_back_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой возврата"""
    keyboard = [
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# ========== ФУНКЦИЯ ОТПРАВКИ ИНВОЙСА ==========
async def send_donation_invoice(
    bot: Bot,
    chat_id: int,
    amount_rub: int
) -> None:
    """
    Отправляет инвойс на оплату через ЮКассу
    Удаляет предыдущий инвойс, если он был
    
    :param bot: Экземпляр бота
    :param chat_id: ID чата пользователя
    :param amount_rub: Сумма в рублях
    """
    # Удаляем предыдущий инвойс, если он был
    if chat_id in last_invoice_messages:
        try:
            await bot.delete_message(chat_id, last_invoice_messages[chat_id])
        except Exception:
            pass  # Игнорируем ошибки удаления (сообщение могло быть уже удалено)
    
    # Telegram Payments API принимает сумму в копейках
    amount_kopeks = amount_rub * 100
    
    prices = [
        LabeledPrice(
            label=f"Пожертвование {amount_rub} ₽",
            amount=amount_kopeks
        )
    ]
    
    # Отправляем новый инвойс и сохраняем его ID
    invoice_message = await bot.send_invoice(
        chat_id=chat_id,
        title=INVOICE_TITLE,
        description=INVOICE_DESCRIPTION,
        payload=f"donation_{amount_rub}",  # Уникальный идентификатор платежа
        provider_token=PAYMENT_PROVIDER_TOKEN,
        currency="RUB",
        prices=prices,
        start_parameter=f"donate_{amount_rub}",
        # Опционально: фото для инвойса (можно добавить своё)
        # photo_url="https://example.com/photo.jpg",
        # photo_width=512,
        # photo_height=512,
    )
    
    # Сохраняем ID нового инвойса
    last_invoice_messages[chat_id] = invoice_message.message_id


# ========== ОБРАБОТЧИКИ ==========

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Обработчик команды /start — отправляет приветствие и меню"""
    # Сбрасываем состояние, если пользователь был в процессе ввода суммы
    await state.clear()
    
    menu_msg = await message.answer(
        text=WELCOME_MESSAGE,
        reply_markup=get_donation_keyboard(),
        parse_mode="HTML"
    )
    # Сохраняем ID сообщения с меню
    last_menu_messages[message.chat.id] = menu_msg.message_id


@router.callback_query(F.data == "back_to_menu")
async def callback_back_to_menu(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    """Возврат в главное меню"""
    await state.clear()
    
    # Удаляем предыдущий инвойс, если он был
    chat_id = callback.message.chat.id
    if chat_id in last_invoice_messages:
        try:
            await bot.delete_message(chat_id, last_invoice_messages[chat_id])
            del last_invoice_messages[chat_id]
        except Exception:
            pass
    
    await callback.message.edit_text(
        text=WELCOME_MESSAGE,
        reply_markup=get_donation_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("donate_") & ~F.data.endswith("custom"))
async def callback_fixed_donation(callback: CallbackQuery, bot: Bot) -> None:
    """Обработчик фиксированных сумм (150, 300, 500, 1000)"""
    # Извлекаем сумму из callback_data
    amount = int(callback.data.split("_")[1])
    
    await callback.answer(f"Формирую счёт на {amount} ₽...")
    
    # Отправляем инвойс
    await send_donation_invoice(bot, callback.message.chat.id, amount)


@router.callback_query(F.data == "donate_custom")
async def callback_custom_donation(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    """Обработчик кнопки 'Ввести свою сумму' — запрашивает ввод"""
    # Удаляем предыдущий инвойс, если он был
    chat_id = callback.message.chat.id
    if chat_id in last_invoice_messages:
        try:
            await bot.delete_message(chat_id, last_invoice_messages[chat_id])
            del last_invoice_messages[chat_id]
        except Exception:
            pass
    
    await state.set_state(DonationStates.waiting_for_amount)
    
    await callback.message.edit_text(
        text=ENTER_AMOUNT_MESSAGE,
        reply_markup=get_back_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(DonationStates.waiting_for_amount)
async def process_custom_amount(message: Message, state: FSMContext, bot: Bot) -> None:
    """Обработчик ввода произвольной суммы"""
    user_input = message.text.strip()
    
    # Проверяем, что ввели число
    if not user_input.isdigit():
        await message.answer(
            text=INVALID_AMOUNT_MESSAGE,
            reply_markup=get_back_keyboard(),
            parse_mode="HTML"
        )
        return
    
    amount = int(user_input)
    
    # Проверяем минимальную сумму
    if amount < MIN_DONATION_AMOUNT:
        await message.answer(
            text=INVALID_AMOUNT_MESSAGE,
            reply_markup=get_back_keyboard(),
            parse_mode="HTML"
        )
        return
    
    # Проверяем максимальную сумму (лимит Telegram — 10000000 копеек = 100000 руб)
    if amount > 100000:
        await message.answer(
            text="❌ <b>Слишком большая сумма!</b>\n\nМаксимум 100 000 ₽",
            reply_markup=get_back_keyboard(),
            parse_mode="HTML"
        )
        return
    
    # Сбрасываем состояние и отправляем инвойс
    await state.clear()
    await send_donation_invoice(bot, message.chat.id, amount)


@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery, bot: Bot) -> None:
    """
    Обработчик PreCheckoutQuery — подтверждаем готовность принять платёж
    Telegram требует ответить в течение 10 секунд
    """
    logger.info(f"PreCheckoutQuery от пользователя {pre_checkout_query.from_user.id}")
    
    # Подтверждаем, что всё ок и можно принимать оплату
    await bot.answer_pre_checkout_query(
        pre_checkout_query_id=pre_checkout_query.id,
        ok=True
    )


@router.message(F.successful_payment)
async def process_successful_payment(message: Message, bot: Bot) -> None:
    """Обработчик успешной оплаты"""
    payment = message.successful_payment
    amount = payment.total_amount // 100  # Переводим из копеек в рубли
    chat_id = message.chat.id
    
    # Удаляем старое меню, если оно было
    if chat_id in last_menu_messages:
        try:
            await bot.delete_message(chat_id, last_menu_messages[chat_id])
            del last_menu_messages[chat_id]
        except Exception:
            pass
    
    # Удаляем сохранённый инвойс (он уже оплачен)
    if chat_id in last_invoice_messages:
        del last_invoice_messages[chat_id]
    
    logger.info(
        f"Успешный платёж от пользователя {message.from_user.id}: "
        f"{amount} ₽ (payload: {payment.invoice_payload})"
    )
    
    # Отправляем благодарственное сообщение с меню для нового доната
    menu_msg = await message.answer(
        text=THANK_YOU_MESSAGE + "\n\n" + "Хочешь поддержать ещё? 👇",
        reply_markup=get_donation_keyboard(),
        parse_mode="HTML"
    )
    # Сохраняем ID нового меню
    last_menu_messages[chat_id] = menu_msg.message_id


# ========== ЗАПУСК БОТА ==========
async def main() -> None:
    """Главная функция запуска бота"""
    # Проверяем, что токены заданы
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("❌ Необходимо указать BOT_TOKEN!")
        return
    
    if PAYMENT_PROVIDER_TOKEN == "YOUR_YUKASSA_PROVIDER_TOKEN_HERE":
        logger.error("❌ Необходимо указать PAYMENT_PROVIDER_TOKEN!")
        return
    
    # Создаём бота и диспетчер
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    
    # Подключаем роутер с обработчиками
    dp.include_router(router)
    
    logger.info("🚀 Бот запущен!")
    
    # Запускаем polling
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
