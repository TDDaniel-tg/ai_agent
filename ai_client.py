import json
from typing import Optional, Tuple

from groq import AsyncGroq

from config import config
from db import get_setting


_client: Optional[AsyncGroq] = None


def get_client() -> AsyncGroq:
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=config.groq_api_key)
    return _client


def _build_system_prompt() -> str:
    stack = get_setting("stack") or config.default_stack
    about = get_setting("about_me") or config.default_about
    min_budget = get_setting("min_budget") or ""

    parts = [
        "You are a freelance job assistant bot. Help the user find and respond to job opportunities.",
        f"\nUser's tech stack: {stack}",
        f"\nAbout the user: {about}",
    ]
    if min_budget:
        parts.append(f"\nMinimum budget filter: {min_budget} USD. Vacancies below this should be rejected.")
    return "\n".join(parts)


async def analyze_vacancy(message_text: str) -> Tuple[bool, float, str, str]:
    prompt = f"""Analyze this Telegram message and determine:
1. Is it a job vacancy/freelance project? (true/false)
2. Relevance score (0.0 to 1.0) based on match with user's stack
3. Brief summary (2-3 sentences)
4. Budget info if mentioned (extract exact amount or range)

Message:
{message_text[:3000]}

Respond ONLY with a valid JSON object:
{{"is_vacancy": bool, "score": float, "summary": str, "budget": str}}"""

    try:
        client = get_client()
        resp = await client.chat.completions.create(
            model=config.groq_model,
            messages=[
                {"role": "system", "content": _build_system_prompt()},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
        return (
            data.get("is_vacancy", False),
            float(data.get("score", 0.0)),
            data.get("summary", ""),
            data.get("budget", ""),
        )
    except Exception as e:
        print(f"[AI] analyze_vacancy error: {e}")
        return False, 0.0, "", ""


async def generate_response(vacancy_text: str) -> Optional[str]:
    prompt = f"""Generate a personalized freelance proposal response for this job vacancy.

Guidelines:
- Be professional and concise
- Highlight relevant experience from user's stack
- Ask clarifying questions if needed
- Keep it under 500 words
- Write in English
- Sign with the user's name (just write Best regards and leave the name blank with _____)

Vacancy:
{vacancy_text[:3000]}

Respond with ONLY the response text, no additional formatting or explanations."""

    try:
        client = get_client()
        resp = await client.chat.completions.create(
            model=config.groq_model,
            messages=[
                {"role": "system", "content": _build_system_prompt()},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"[AI] generate_response error: {e}")
        return None


async def classify_channel(title: str, about: str = "") -> Tuple[bool, float, str]:
    prompt = f"""Analyze this Telegram channel and determine:
1. Is it likely a freelance/job vacancy channel? (true/false)
2. Confidence score (0.0 to 1.0)
3. Category (one word: "freelance", "tech_jobs", "general_jobs", "other")

Channel title: {title}
Channel description: {about[:500]}

Respond ONLY with a valid JSON object:
{{"is_job_channel": bool, "score": float, "category": str}}"""

    try:
        client = get_client()
        resp = await client.chat.completions.create(
            model=config.groq_model,
            messages=[
                {"role": "system", "content": "You classify Telegram channels by topic."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
        return (
            data.get("is_job_channel", False),
            float(data.get("score", 0.0)),
            data.get("category", "other"),
        )
    except Exception as e:
        print(f"[AI] classify_channel error: {e}")
        return False, 0.0, "other"


async def generate_followup(vacancy_text: str, previous_response: Optional[str] = None) -> Optional[str]:
    prompt = f"""Generate a polite follow-up message for a job application.

Context: You sent a proposal for a freelance vacancy but haven't heard back.
Be polite, not pushy. Ask if they need any additional information.

Original vacancy:
{vacancy_text[:2000]}

Previous response:
{previous_response or 'No previous response'}

Respond with ONLY the follow-up message text, no additional formatting."""

    try:
        client = get_client()
        resp = await client.chat.completions.create(
            model=config.groq_model,
            messages=[
                {"role": "system", "content": _build_system_prompt()},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"[AI] generate_followup error: {e}")
        return None
