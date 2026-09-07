from bot.config import BOT_TOKEN


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")
    print("Bot skeleton is ready. Add your framework and handlers here.")


if __name__ == "__main__":
    main()
