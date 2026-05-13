import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    bot_token: str = os.getenv("BOT_TOKEN", "")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    admin_user_id: int = int(os.getenv("ADMIN_USER_ID", "0"))
    db_path: str = os.getenv("DB_PATH", "freelance_bot.db")
    groq_model: str = "llama-3.3-70b-versatile"
    max_accounts: int = 3
    followup_days: int = int(os.getenv("FOLLOWUP_DAYS", "3"))
    ping_url: str = os.getenv("PING_URL", "")
    port: int = int(os.getenv("PORT", "8080"))
    session_dir: str = os.getenv("SESSION_DIR", "sessions")
    min_budget: Optional[int] = None

    default_stack: str = (
        "Python, FastAPI, Django, SQLAlchemy, Celery, "
        "React Native, Flutter, Web Scraping (BeautifulSoup, Scrapy, Playwright), "
        "AI/ML (scikit-learn, PyTorch, LangChain, LlamaIndex), "
        "PostgreSQL, Redis, Docker, AWS"
    )
    default_about: str = (
        "Backend Python developer with 5+ years experience. "
        "Strong in API design, data processing, and automation. "
        "Built multiple ETL pipelines, chatbots, and web scraping systems. "
        "Experience with freelancing platforms and client communication."
    )


config = Config()
