import config
from bot import bot, logger

if __name__ == "__main__":
    if not config.DISCORD_TOKEN:
        logger.error("ОШИБКА: Токен бота не указан в config.py или файле .env!")
    else:
        bot.run(config.DISCORD_TOKEN)
