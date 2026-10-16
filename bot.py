import asyncio
import logging
import os
import discord
from discord import app_commands
from discord.ext import commands

import config
from rules_checker import RulesChecker, RuleViolation

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("RuleGuard")

# Инициализация Gemini AI (если указан GEMINI_API_KEY)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
gemini_client = None
if GEMINI_API_KEY:
    try:
        from google import genai
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        logger.info("Подключен модуль Gemini AI для глубокой проверки сообщений!")
    except Exception as e:
        logger.warning(f"Не удалось инициализировать Gemini AI: {e}")

# Инициализация проверки локальных правил
checker = RulesChecker(
    politics_channel=config.POLITICS_CHANNEL_KEYWORD,
    flood_channel=config.FLOOD_CHANNEL_KEYWORD
)

TARGET_GUILD_NAME = os.getenv("TARGET_GUILD_NAME", "all").lower()


async def check_with_ai(content: str, channel_name: str) -> tuple[str, str] | None:
    """Проверяет сообщение через Gemini AI при наличии API-ключа.
    Возвращает (rule_code, reason) или None, если нарушений нет."""
    if not gemini_client or not content or len(content.strip()) < 3:
        return None

    prompt = f"""Ты — строгий AI-модератор Discord-сервера "cult of browny".
Оцени следующее сообщение участника на предмет явных или скрытых нарушений правил сервера:

Список правил сервера:
п:2.0 Твинководство (обход ограничений, использование твинков)
п:3.1 Прямые оскорбления, травля, грубые наезды, токсичность
п:3.2 Провокация конфликтов, розжиг ссор
п:3.3 Токсичное поведение, агрессия
п:4.0 Дискриминация, разжигание ненависти, бан-ворды (п-ворды, н-ворды, шовинизм)
п:5.0 Доксинг, деанон, сливы личных данных (сливы фото, переписок, баз данных, номеров, адресов, пробив, сваттинг)
п:6.0 NSFW/NSFL контент (18+, порно, хентай, расчлененка, шок-контент)
п:8.0 Политические срачи (разрешены исключительно в канале дискуссий)
п:9.0 Реклама сторонних серверов/каналов (ссылки discord.gg, t.me)
п:10.0 Спам и флуд
п:12.0 Выдача себя за администрацию или модерацию
п:14.0 Реальные угрозы расправой, шантаж, сваттинг, призывы к насилию
п:15.0 Фишинг, скам, продажа аккаунтов, вредоносные ссылки
п:16.0 Злоупотребление упоминаниями (@everyone, @here, массовые пинги)
п:19.0 Шутки и мемы про трагедии/драмы, суициды, шок-контент, картели, расправы и стрельбу (я родился богом, родился богом, я бог, пантера, сердцеед, нинада, олешки, голда, коч, 1444, глеб кораблев, пока пацаны, ронни макнатт/mcnutt, фанкитаун/funkytown, рина паленкова/ня пока, артем исхаков/страхова, росляков, галявиев, бекмансуров, колумбайн, скулшутинг, крокус, беслан, зимняя вишня, норд-ост, башни близнецы, 3 guys 1 hammer, чикатило, пичушкин, синий кит, no mercy in mexico, сплит и любые подобные аморальные мемы)

Канал: #{channel_name}
Текст сообщения: "{content}"

Если сообщение НАРУШАЕТ правила, ответь строго в формате:
ДА п:X.Y | Краткая причина нарушения

Если сообщение НЕ нарушает правила, ответь строго одним словом:
НЕТ"""

    for model_name in ("gemini-flash-lite-latest", "gemini-3.5-flash"):
        try:
            response = await gemini_client.aio.models.generate_content(
                model=model_name,
                contents=prompt
            )
            text = response.text.strip()
            if text.upper().startswith("ДА"):
                parts = text.split("|", 1)
                code_part = parts[0].replace("ДА", "").strip()
                reason = parts[1].strip() if len(parts) > 1 else "Нарушение правил"
                return (code_part, reason)
            return None
        except Exception as e:
            logger.warning(f"Ошибка Gemini ({model_name}): {e}")
    return None


async def send_violation_alert(message: discord.Message, verdict: str, details: str, trigger: str = "", is_ai: bool = False):
    author = message.author
    guild = message.guild
    channel = message.channel

    embed = discord.Embed(
        title=f"Нарушение: {verdict}",
        color=0x2B2D31,
        timestamp=message.created_at
    )

    guild_name = guild.name if guild else "cult of browny"
    ch_name = getattr(channel, "name", "чат")
    embed.add_field(name="Откуда:", value=f"{guild_name} • #{ch_name}", inline=False)
    embed.add_field(
        name="Автор",
        value=f"{author.mention}\nЮз: @{author.name}\nНик: {author.display_name}\nID: {author.id}",
        inline=True
    )
    if trigger:
        embed.add_field(name="Триггер", value=f"`{trigger}`", inline=True)
    if details:
        embed.add_field(name="Почему", value=details, inline=False)

    clean_content = message.content or "[без текста / вложение]"
    if len(clean_content) > 1000:
        clean_content = clean_content[:997] + "..."
    embed.add_field(name="Сообщение", value=f"```{clean_content}```", inline=False)

    if message.attachments:
        att_links = [f"[{att.filename}]({att.url})" for att in message.attachments]
        embed.add_field(name="Вложения", value=", ".join(att_links), inline=False)

    view = discord.ui.View()
    if message.jump_url:
        view.add_item(discord.ui.Button(label="Перейти к сообщению", url=message.jump_url, style=discord.ButtonStyle.link))

    for uid in config.MODERATOR_USER_IDS:
        user = bot.get_user(uid)
        if not user:
            try:
                user = await bot.fetch_user(uid)
            except Exception:
                pass
        if user:
            try:
                await user.send(embed=embed, view=view)
                logger.info(f"Алерт отправлен в ЛС: {user.name} ({user.id})")
            except Exception as e:
                logger.error(f"Ошибка отправки алерта {user.name}: {e}")


def create_bot(with_message_content: bool = True) -> commands.Bot:
    intents = discord.Intents.default()
    if with_message_content:
        intents.message_content = True

    b = commands.Bot(command_prefix=":", intents=intents)

    @b.event
    async def on_ready():
        try:
            synced = await b.tree.sync()
            logger.info(f"Синхронизировано команд и контекстных меню: {len(synced)}")
        except Exception as e:
            logger.error(f"Ошибка синхронизации команд: {e}")

        logger.info(f"Бот успешно запущен как {b.user} (ID: {b.user.id})")
        logger.info(f"Мониторинг сервера: '{TARGET_GUILD_NAME}' активен.")
        for g in b.guilds:
            logger.info(f"Подключен к серверу: '{g.name}' (ID: {g.id})")

    @b.event
    async def on_message(message: discord.Message):
        # Игнорируем ботов и сообщения вне серверов
        if message.author.bot or not message.guild:
            return

        # Если это скрытая команда с префиксом ':', выполняем её и не проверяем на нарушения
        if message.content.startswith(":"):
            await b.process_commands(message)
            return

        # Фильтруем сервер (если в .env указано 'all' или пусто — проверяем все серверы)
        if TARGET_GUILD_NAME and TARGET_GUILD_NAME not in ("all", "*"):
            allowed_guilds = [g.strip() for g in TARGET_GUILD_NAME.split(",") if g.strip()]
            if not any(g in message.guild.name.lower() for g in allowed_guilds):
                return

        # Логируем входящее сообщение
        if not message.content:
            logger.warning(f"[{message.guild.name}][#{message.channel.name}] Сообщение от {message.author} пришло с ПУСТЫМ текстом! Причина: тумблер 'Message Content Intent' выключен в Discord Developer Portal.")
        else:
            logger.info(f"[{message.guild.name}][#{message.channel.name}] Получено сообщение от {message.author}: '{message.content}'")

        # 1. Быстрая жесткая проверка по правилам (банворды, леетспик, регулярки)
        violations = checker.check_message(
            content=message.content,
            channel_name=getattr(message.channel, "name", "чат"),
            author_id=message.author.id,
            mentions_count=len(message.mentions),
            has_everyone=getattr(message, "mention_everyone", False)
        )

        if violations:
            top_v = violations[0]
            verdict = f"ДА {top_v.rule_code} ({top_v.rule_name})"
            logger.info(f"[{message.guild.name}][#{message.channel.name}] Нарушение от {message.author}: {verdict}")
            await send_violation_alert(message, verdict=verdict, details=top_v.details, trigger=top_v.matched_word, is_ai=False)
            return

        # 2. Если локальные регулярки не сработали, но подключен Gemini AI - проверяем контекст через AI
        if gemini_client and message.content:
            ai_res = await check_with_ai(message.content, getattr(message.channel, "name", "чат"))
            if ai_res:
                code, reason = ai_res
                verdict = f"ДА {code} (ИИ)"
                logger.info(f"[{message.guild.name}][#{message.channel.name}] AI обнаружил нарушение от {message.author}: {verdict}")
                await send_violation_alert(message, verdict=verdict, details=reason, trigger="", is_ai=True)

        await b.process_commands(message)

    # Контекстное меню сообщения
    @b.tree.context_menu(name="Проверить сообщение")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def check_message_context(interaction: discord.Interaction, message: discord.Message):
        await interaction.response.defer(ephemeral=True)

        guild_name = message.guild.name if message.guild else "cult of browny"
        ch_name = getattr(message.channel, "name", "чат")

        violations = checker.check_message(
            content=message.content,
            channel_name=ch_name,
            author_id=message.author.id,
            mentions_count=len(message.mentions),
            has_everyone=getattr(message, "mention_everyone", False)
        )

        if violations:
            top_v = violations[0]
            verdict = f"ДА {top_v.rule_code} ({top_v.rule_name})"
            embed = discord.Embed(
                title=f"Нарушение: {verdict}",
                color=0x2B2D31
            )
            embed.add_field(name="Откуда:", value=f"{guild_name} • #{ch_name}", inline=False)
            embed.add_field(
                name="Автор",
                value=f"{message.author.mention}\nЮз: @{message.author.name}\nНик: {message.author.display_name}\nID: {message.author.id}",
                inline=True
            )
            if top_v.matched_word:
                embed.add_field(name="Триггер", value=f"`{top_v.matched_word}`", inline=True)
            embed.add_field(name="Почему", value=top_v.details, inline=False)
            clean = message.content or "[без текста / вложение]"
            embed.add_field(name="Сообщение", value=f"```{clean[:800]}```", inline=False)
            view = discord.ui.View()
            if message.jump_url:
                view.add_item(discord.ui.Button(label="Перейти к сообщению", url=message.jump_url, style=discord.ButtonStyle.link))
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            return

        if gemini_client and message.content:
            ai_res = await check_with_ai(message.content, ch_name)
            if ai_res:
                code, reason = ai_res
                verdict = f"ДА {code} (ИИ)"
                embed = discord.Embed(
                    title=f"Нарушение: {verdict}",
                    color=0x2B2D31
                )
                embed.add_field(name="Откуда:", value=f"{guild_name} • #{ch_name}", inline=False)
                embed.add_field(
                    name="Автор",
                    value=f"{message.author.mention}\nЮз: @{message.author.name}\nНик: {message.author.display_name}\nID: {message.author.id}",
                    inline=True
                )
                embed.add_field(name="Почему", value=reason, inline=False)
                clean = message.content or "[без текста / вложение]"
                embed.add_field(name="Сообщение", value=f"```{clean[:800]}```", inline=False)
                view = discord.ui.View()
                if message.jump_url:
                    view.add_item(discord.ui.Button(label="Перейти к сообщению", url=message.jump_url, style=discord.ButtonStyle.link))
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
                return

        await interaction.followup.send(f"Нарушений не обнаружено: {message.author.mention}.", ephemeral=True)

    # Скрытая префикс-команда
    @b.command(name="test_rules", aliases=["test"])
    async def cmd_test_rules(ctx: commands.Context, *, text: str = ""):
        if not text:
            await ctx.reply("Использование: `:test <текст>`", delete_after=5)
            return

        violations = checker.check_message(
            content=text,
            channel_name=getattr(ctx.channel, "name", "общий"),
            author_id=ctx.author.id,
            mentions_count=0,
            has_everyone=False
        )
        if violations:
            top_v = violations[0]
            await ctx.reply(f"Вердикт: ДА {top_v.rule_code} ({top_v.rule_name}) | `{top_v.matched_word}` — {top_v.details}")
            return

        if gemini_client:
            ai_res = await check_with_ai(text, getattr(ctx.channel, "name", "общий"))
            if ai_res:
                code, reason = ai_res
                await ctx.reply(f"Вердикт: ДА {code} (ИИ) | {reason}")
                return
            await ctx.reply("Вердикт: НЕТ")
            return

        await ctx.reply("Вердикт: НЕТ")

    return b


bot = create_bot(with_message_content=True)


if __name__ == "__main__":
    if not config.DISCORD_TOKEN:
        logger.error("ОШИБКА: Токен бота не указан в config.py или файле .env!")
    else:
        try:
            bot.run(config.DISCORD_TOKEN)
        except discord.errors.PrivilegedIntentsRequired:
            logger.warning(
                "\n" + "=" * 65 + "\n"
                "⚠️ Внимание: Message Content Intent выключен на портале Discord!\n"
                "Чтобы бот автоматически сканировал чаты сервера 'cult of browny',\n"
                "включите тумблер 'Message Content Intent' в Developer Portal:\n"
                "https://discord.com/developers/applications/1560610957103730830/bot\n\n"
                "Запускаем бота без привилегированных интентов (режим Context Menu)...\n"
                + "=" * 65 + "\n"
            )
            bot = create_bot(with_message_content=False)
            bot.run(config.DISCORD_TOKEN)
