import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ChatPermissions
)
from datetime import datetime, timedelta

from ..database import Database
from ..config import BotSettings

logger = logging.getLogger(__name__)
router = Router(name="admin_router")


async def is_admin(message_or_query: Message | CallbackQuery, settings: BotSettings) -> bool:
    user_id = message_or_query.from_user.id
    if user_id in settings.ADMIN_IDS:
        return True

    # If in a group / supergroup, check chat administrator rights
    chat = message_or_query.message.chat if isinstance(message_or_query, CallbackQuery) else message_or_query.chat
    if chat.type in ["group", "supergroup", "channel"]:
        try:
            bot = message_or_query.bot
            member = await bot.get_chat_member(chat.id, user_id)
            return member.status in ["creator", "administrator"]
        except Exception as e:
            logger.warning(f"Error checking admin status: {e}")
            return False
    return False


def build_settings_keyboard(chat_settings: dict) -> InlineKeyboardMarkup:
    def mark(val: int) -> str:
        return "ВКЛ ✅" if val else "ВЫКЛ ❌"

    buttons = [
        [
            InlineKeyboardButton(
                text=f"🔞 Порно: {mark(chat_settings.get('anti_porn', 1))}",
                callback_data="toggle_anti_porn"
            ),
            InlineKeyboardButton(
                text=f"🚫 Спам: {mark(chat_settings.get('anti_spam', 1))}",
                callback_data="toggle_anti_spam"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"⚡ Флуд: {mark(chat_settings.get('anti_flood', 1))}",
                callback_data="toggle_anti_flood"
            ),
            InlineKeyboardButton(
                text=f"🔗 Ссылки: {mark(chat_settings.get('anti_links', 1))}",
                callback_data="toggle_anti_links"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"🌐 Арабский/Спам-шрифт: {mark(chat_settings.get('anti_foreign', 1))}",
                callback_data="toggle_anti_foreign"
            ),
            InlineKeyboardButton(
                text=f"🤬 Мат: {mark(chat_settings.get('anti_profanity', 1))}",
                callback_data="toggle_anti_profanity"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"🧹 Служебные смс: {mark(chat_settings.get('delete_service', 1))}",
                callback_data="toggle_delete_service"
            ),
            InlineKeyboardButton(
                text=f"📷 Запрет медиа: {mark(chat_settings.get('block_media', 0))}",
                callback_data="toggle_block_media"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"🤫 Тихий режим: {mark(chat_settings.get('silent_mode', 1))}",
                callback_data="toggle_silent_mode"
            ),
            InlineKeyboardButton(
                text=f"⚔ Наказание: {chat_settings.get('action_on_violation', 'delete').upper()}",
                callback_data="cycle_action"
            )
        ],
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="show_stats"),
            InlineKeyboardButton(text="📝 Стоп-слова", callback_data="show_words")
        ],
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_settings")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(Command("settings", "panel"))
async def cmd_settings(message: Message, db: Database, settings: BotSettings):
    if not await is_admin(message, settings):
        return await message.reply("⛔ Эта команда доступна только администраторам канала/чата.")

    chat_id = message.chat.id
    chat_title = message.chat.title or message.chat.username or "Личный диалог"
    cfg = await db.get_chat_settings(chat_id, title=chat_title)

    text = (
        f"⚙️ <b>Панель управления цензурой и антиспамом</b>\n"
        f"💬 Чат / Канал: <b>{chat_title}</b> (<code>{chat_id}</code>)\n\n"
        f"Нажмите на кнопку, чтобы включить/выключить нужный фильтр:"
    )
    kb = build_settings_keyboard(cfg)
    await message.reply(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("toggle_"))
async def callback_toggle(query: CallbackQuery, db: Database, settings: BotSettings):
    if not await is_admin(query, settings):
        return await query.answer("⛔ Недостаточно прав!", show_alert=True)

    chat_id = query.message.chat.id
    key = query.data.replace("toggle_", "")
    cfg = await db.get_chat_settings(chat_id)

    curr_val = cfg.get(key, 1)
    new_val = 0 if curr_val else 1
    await db.update_chat_setting(chat_id, key, new_val)

    updated_cfg = await db.get_chat_settings(chat_id)
    await query.message.edit_reply_markup(reply_markup=build_settings_keyboard(updated_cfg))
    await query.answer(f"Параметр {key} изменен на {'ВКЛ' if new_val else 'ВЫКЛ'}")


@router.callback_query(F.data == "cycle_action")
async def callback_cycle_action(query: CallbackQuery, db: Database, settings: BotSettings):
    if not await is_admin(query, settings):
        return await query.answer("⛔ Недостаточно прав!", show_alert=True)

    chat_id = query.message.chat.id
    cfg = await db.get_chat_settings(chat_id)

    actions = ["delete", "warn", "mute_1h", "mute_24h", "ban"]
    curr = cfg.get("action_on_violation", "delete")
    try:
        next_idx = (actions.index(curr) + 1) % len(actions)
    except ValueError:
        next_idx = 0

    new_action = actions[next_idx]
    await db.update_chat_setting(chat_id, "action_on_violation", new_action)

    updated_cfg = await db.get_chat_settings(chat_id)
    await query.message.edit_reply_markup(reply_markup=build_settings_keyboard(updated_cfg))
    await query.answer(f"Действие при нарушении: {new_action}")


@router.callback_query(F.data == "refresh_settings")
async def callback_refresh(query: CallbackQuery, db: Database):
    chat_id = query.message.chat.id
    cfg = await db.get_chat_settings(chat_id)
    await query.message.edit_reply_markup(reply_markup=build_settings_keyboard(cfg))
    await query.answer("Настройки обновлены")


@router.callback_query(F.data == "show_stats")
async def callback_stats(query: CallbackQuery, db: Database):
    chat_id = query.message.chat.id
    stats = await db.get_chat_stats(chat_id)
    
    lines = [f"📊 <b>Статистика фильтрации:</b>", f"Всего удалено спама: <b>{stats['total_deleted']}</b>"]
    if stats["top_reasons"]:
        lines.append("\n<b>Топ причин нарушений:</b>")
        for reason, count in stats["top_reasons"]:
            lines.append(f"• {reason}: {count}")
            
    await query.answer()
    await query.message.reply("\n".join(lines), parse_mode="HTML")


@router.callback_query(F.data == "show_words")
async def callback_words(query: CallbackQuery, db: Database):
    chat_id = query.message.chat.id
    bl = await db.get_custom_words(chat_id, "blacklist")
    wl = await db.get_whitelisted_domains(chat_id)
    
    bl_str = ", ".join(bl) if bl else "<i>(нет слов в черном списке)</i>"
    wl_str = ", ".join(wl) if wl else "<i>(нет разрешенных ссылок)</i>"

    text = (
        f"📝 <b>Пользовательские фильтры чата:</b>\n\n"
        f"🚫 <b>Черный список слов:</b>\n{bl_str}\n\n"
        f"Добавить: <code>/addword слово</code>\n"
        f"Удалить: <code>/delword слово</code>\n\n"
        f"✅ <b>Белый список доменов/ссылок:</b>\n{wl_str}\n\n"
        f"Добавить: <code>/addwhitelist домен</code>\n"
        f"Удалить: <code>/delwhitelist домен</code>"
    )
    await query.answer()
    await query.message.reply(text, parse_mode="HTML")


# ---------------- Custom Words Management ---------------- #

@router.message(Command("addword"))
async def cmd_addword(message: Message, db: Database, settings: BotSettings):
    if not await is_admin(message, settings):
        return await message.reply("⛔ Только для администраторов.")

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply("Использование: <code>/addword запрещенное_слово</code>", parse_mode="HTML")

    word = parts[1].strip()
    success = await db.add_custom_word(message.chat.id, word, "blacklist")
    if success:
        await message.reply(f"✅ Слово <b>«{word}»</b> добавлено в черный список чата.", parse_mode="HTML")
    else:
        await message.reply("⚠️ Это слово уже есть в черном списке.")


@router.message(Command("delword"))
async def cmd_delword(message: Message, db: Database, settings: BotSettings):
    if not await is_admin(message, settings):
        return await message.reply("⛔ Только для администраторов.")

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply("Использование: <code>/delword слово</code>", parse_mode="HTML")

    word = parts[1].strip()
    success = await db.remove_custom_word(message.chat.id, word, "blacklist")
    if success:
        await message.reply(f"🗑 Слово <b>«{word}»</b> удалено из черного списка.", parse_mode="HTML")
    else:
        await message.reply("⚠️ Слово не найдено в черном списке.")


@router.message(Command("words", "blacklist"))
async def cmd_words(message: Message, db: Database, settings: BotSettings):
    if not await is_admin(message, settings):
        return await message.reply("⛔ Только для администраторов.")

    words = await db.get_custom_words(message.chat.id, "blacklist")
    if not words:
        return await message.reply("📝 Черный список слов пуст.")
    
    text = "🚫 <b>Черный список слов:</b>\n" + "\n".join(f"• {w}" for w in words)
    await message.reply(text, parse_mode="HTML")


@router.message(Command("addwhitelist"))
async def cmd_addwhitelist(message: Message, db: Database, settings: BotSettings):
    if not await is_admin(message, settings):
        return await message.reply("⛔ Только для администраторов.")

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply("Использование: <code>/addwhitelist домен_или_ник</code>\nПример: <code>/addwhitelist vorondolls</code> или <code>/addwhitelist vk.com</code>", parse_mode="HTML")

    domain = parts[1].strip().lower().replace("https://", "").replace("http://", "").rstrip('/')
    success = await db.add_whitelisted_domain(message.chat.id, domain)
    if success:
        await message.reply(f"✅ Домен/ссылка <b>«{domain}»</b> добавлена в белый список.", parse_mode="HTML")
    else:
        await message.reply("⚠️ Этот домен уже в белом списке.")


@router.message(Command("delwhitelist"))
async def cmd_delwhitelist(message: Message, db: Database, settings: BotSettings):
    if not await is_admin(message, settings):
        return await message.reply("⛔ Только для администраторов.")

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply("Использование: <code>/delwhitelist домен</code>", parse_mode="HTML")

    domain = parts[1].strip().lower()
    success = await db.remove_whitelisted_domain(message.chat.id, domain)
    if success:
        await message.reply(f"🗑 <b>«{domain}»</b> удален из белого списка.", parse_mode="HTML")
    else:
        await message.reply("⚠️ Домен не найден в белом списке.")


@router.message(Command("whitelist"))
async def cmd_whitelist(message: Message, db: Database, settings: BotSettings):
    if not await is_admin(message, settings):
        return await message.reply("⛔ Только для администраторов.")

    domains = await db.get_whitelisted_domains(message.chat.id)
    if not domains:
        return await message.reply("✅ Белый список ссылок пуст.")
    
    text = "✅ <b>Белый список разрешенных доменов/ссылок:</b>\n" + "\n".join(f"• {d}" for d in domains)
    await message.reply(text, parse_mode="HTML")


# ---------------- Manual Admin Commands: Ban, Mute, Unmute ---------------- #

@router.message(Command("ban"))
async def cmd_ban(message: Message, settings: BotSettings):
    if not await is_admin(message, settings):
        return await message.reply("⛔ Только для администраторов.")
    
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return await message.reply("⚠️ Ответьте этой командой на сообщение нарушителя, которого хотите забанить.")

    target = message.reply_to_message.from_user
    try:
        await message.chat.ban_chat_member(target.id)
        await message.reply(f"🚫 Пользователь <b>{target.full_name}</b> (<code>{target.id}</code>) заблокирован.", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Не удалось забанить: {e}")


@router.message(Command("mute"))
async def cmd_mute(message: Message, settings: BotSettings):
    if not await is_admin(message, settings):
        return await message.reply("⛔ Только для администраторов.")
    
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return await message.reply("⚠️ Ответьте на сообщение пользователя: <code>/mute 60</code> (на 60 минут)", parse_mode="HTML")

    parts = message.text.split()
    minutes = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 60

    target = message.reply_to_message.from_user
    until_date = datetime.now() + timedelta(minutes=minutes)

    try:
        await message.chat.restrict(
            user_id=target.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until_date
        )
        await message.reply(f"🔇 Пользователь <b>{target.full_name}</b> переведен в режим только для чтения на {minutes} мин.", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Ошибка мута: {e}")


@router.message(Command("unmute", "unban"))
async def cmd_unmute(message: Message, settings: BotSettings):
    if not await is_admin(message, settings):
        return await message.reply("⛔ Только для администраторов.")
    
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return await message.reply("⚠️ Ответьте на сообщение пользователя.")

    target = message.reply_to_message.from_user
    try:
        await message.chat.restrict(
            user_id=target.id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True
            )
        )
        await message.reply(f"🔊 Ограничения с пользователя <b>{target.full_name}</b> сняты.", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")


@router.message(Command("stats"))
async def cmd_stats(message: Message, db: Database, settings: BotSettings):
    if not await is_admin(message, settings):
        return await message.reply("⛔ Только для администраторов.")

    stats = await db.get_chat_stats(message.chat.id)
    lines = [f"📊 <b>Статистика фильтрации:</b>", f"Всего удалено спама: <b>{stats['total_deleted']}</b>"]
    if stats["top_reasons"]:
        lines.append("\n<b>Топ причин нарушений:</b>")
        for reason, count in stats["top_reasons"]:
            lines.append(f"• {reason}: {count}")
            
    await message.reply("\n".join(lines), parse_mode="HTML")


@router.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        "🤖 <b>Бот-цензор и антиспам для канала и чатов</b>\n\n"
        "<b>Команды администратора:</b>\n"
        "• <code>/settings</code> или <code>/panel</code> — Интерактивная панель настройки фильтров\n"
        "• <code>/addword [слово]</code> — Добавить слово в черный список\n"
        "• <code>/delword [слово]</code> — Удалить слово из черного списка\n"
        "• <code>/words</code> — Список стоп-слов\n"
        "• <code>/addwhitelist [домен]</code> — Добавить домен/ссылку в белый список\n"
        "• <code>/delwhitelist [домен]</code> — Удалить из белого списка\n"
        "• <code>/whitelist</code> — Белый список ссылок\n"
        "• <code>/stats</code> — Статистика заблокированного спама\n"
        "• <code>/mute [минут]</code> — Замутить пользователя (ответом на смс)\n"
        "• <code>/unmute</code> — Размутить пользователя\n"
        "• <code>/ban</code> — Заблокировать нарушителя\n\n"
        "<i>Бот автоматически защищает комментарии канала от порно, спама, рекламы, левых ссылок, флуда и ботов.</i>"
    )
    await message.reply(text, parse_mode="HTML")
