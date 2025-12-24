from datetime import datetime, timedelta
import logging

import google.generativeai as genai
from sqlmodel import Session, select

from app.config import settings
from app.storage import ApprovedTeaserExample
from app.mastodon_client import get_trending_hashtags

logger = logging.getLogger(__name__)


# Use a cheaper / faster default model, overridable via environment variable
DEFAULT_GOOGLE_MODEL = "models/gemini-2.5-flash-lite"
DEFAULT_GOOGLE_SUMMARY_MODEL = "models/gemini-2.0-flash-lite"
MODEL_NAME = getattr(settings, "google_model_name", DEFAULT_GOOGLE_MODEL)
SUMMARY_MODEL_NAME = getattr(
    settings,
    "google_summary_model_name",
    DEFAULT_GOOGLE_SUMMARY_MODEL,
)

# Tunable guards for long-form articles
LONG_ARTICLE_CHAR_THRESHOLD = getattr(
    settings,
    "teaser_summary_threshold_chars",
    4000,
)
SUMMARY_TARGET_LENGTH = getattr(
    settings,
    "teaser_summary_target_chars",
    1200,
)
SUMMARY_PROMPT_MAX_CHARS = getattr(
    settings,
    "teaser_summary_prompt_limit",
    6000,
)

model = None
summary_model = None
if settings.google_api_key:
    genai.configure(api_key=settings.google_api_key)
    model = genai.GenerativeModel(MODEL_NAME)
    # Avoid instantiating the same model twice
    if SUMMARY_MODEL_NAME == MODEL_NAME:
        summary_model = model
    else:
        summary_model = genai.GenerativeModel(SUMMARY_MODEL_NAME)

# Cache for trending hashtags (fetched once per day)
_trending_hashtags_cache: list[dict] = []
_trending_hashtags_cache_time: datetime | None = None
CACHE_DURATION = timedelta(hours=24)  # Cache for 24 hours

def fetch_and_cache_trending_hashtags() -> list[dict]:
    """
    Fetches trending hashtags from Mastodon and caches them.
    This should be called once per day via the scheduler.
    """
    global _trending_hashtags_cache, _trending_hashtags_cache_time
    try:
        logger.info("Fetching trending hashtags from Mastodon")
        trending = get_trending_hashtags(limit=20)
        _trending_hashtags_cache = trending
        _trending_hashtags_cache_time = datetime.utcnow()
        logger.info(
            "Successfully cached trending hashtags",
            extra={"count": len(trending)},
        )
        return trending
    except Exception:
        logger.exception("Error fetching trending hashtags")
        return []

def get_cached_trending_hashtags() -> list[dict]:
    """
    Returns cached trending hashtags if they're still fresh, otherwise returns empty list.
    Use fetch_and_cache_trending_hashtags() to refresh the cache.
    """
    global _trending_hashtags_cache, _trending_hashtags_cache_time
    
    if _trending_hashtags_cache_time is None:
        return []
    
    # Check if cache is still valid
    age = datetime.utcnow() - _trending_hashtags_cache_time
    if age < CACHE_DURATION:
        return _trending_hashtags_cache
    else:
        # Cache expired, return empty (will be refreshed by scheduler)
        return []

def _truncate_text(text: str, limit: int, add_ellipsis: bool = True) -> str:
    if len(text) <= limit:
        return text
    clipped = text[:limit].rstrip()
    return f"{clipped}..." if add_ellipsis else clipped


def _prepare_teaser_source(description: str) -> str:
    """
    If the article is especially long, summarize it with a cheaper model so the
    final teaser prompt stays focused.
    """
    if len(description) <= LONG_ARTICLE_CHAR_THRESHOLD:
        return description
    logger.info(
        "Article exceeds teaser threshold, summarizing before teaser generation",
        extra={"length": len(description)},
    )
    return _summarize_long_article(description)


def _summarize_long_article(description: str) -> str:
    """
    Summarizes the article with Gemini 2.0 flash lite (cheaper, handles longer
    inputs). Falls back to local truncation when the model isn't available.
    """
    clipped_description = _truncate_text(
        description,
        SUMMARY_PROMPT_MAX_CHARS,
        add_ellipsis=False,
    )

    if not summary_model:
        return _truncate_text(clipped_description, SUMMARY_TARGET_LENGTH)

    prompt = (
        "Summarize the following article into a concise, neutral overview that "
        f"preserves the key hook, names, and numbers. Keep it under "
        f"{SUMMARY_TARGET_LENGTH} characters. Return plan text only. No emojis.\n\n"
        f"{clipped_description}"
    )

    try:
        response = summary_model.generate_content(prompt)
        summarized = (response.text or "").strip()
        if summarized:
            return summarized
    except Exception:
        logger.exception("Error summarizing long article for teaser prep")
    return _truncate_text(clipped_description, SUMMARY_TARGET_LENGTH)


def generate_teaser(description: str, max_length: int = 200) -> str:
    """
    Generates a teaser from the article description using a generative AI model.
    Long inputs are summarized first with a cheaper model to keep prompts short.
    """
    prepared_description = _prepare_teaser_source(description)

    if not model:
        logger.warning(
            "GOOGLE_API_KEY is not set. Falling back to simple truncation for teaser generation"
        )
        return _truncate_text(prepared_description, max_length)

    try:
        prompt = (
            "Generate a super engaging, concise, and personal social media "
            "teaser for the following article. The teaser should be ready to "
            f"use, without any introductory phrases or options, and less than "
            f"{max_length} characters.\n\n{prepared_description}"
        )
        response = model.generate_content(prompt)
        return response.text
    except Exception:
        logger.exception("Error generating teaser with AI")
        return _truncate_text(prepared_description, max_length)

def find_relevant_trending_hashtags(
    article_title: str, 
    article_description: str, 
    trending_hashtags: list[dict],
    max_results: int = 3
) -> list[str]:
    """
    Uses AI to determine which trending hashtags are relevant to an article.
    Returns a list of relevant hashtag names (without the # symbol).
    """
    if not settings.google_api_key:
        return []
    
    if not trending_hashtags:
        return []
    
    # Extract hashtag names from the trending data
    hashtag_names = [tag.get('name', '').lstrip('#') for tag in trending_hashtags if tag.get('name')]
    
    if not hashtag_names:
        return []
    
    prompt = f"""Given the following article:
Title: {article_title}
Description: {article_description[:500]}

And these currently trending hashtags on Mastodon:
{', '.join(hashtag_names)}

Identify which trending hashtags are relevant to this article. Only select hashtags that genuinely relate to the article's topic, theme, or subject matter. Return ONLY a comma-separated list of relevant hashtag names (without # symbols), or "none" if none are relevant. Maximum {max_results} hashtags."""

    try:
        response = model.generate_content(prompt)
        result = response.text.strip().lower()
        
        if result == "none" or not result:
            return []
        
        # Parse the response and validate against the original list
        suggested_tags = [tag.strip().lstrip('#') for tag in result.split(',')]
        # Normalize both lists for comparison (lowercase)
        hashtag_names_lower = [name.lower() for name in hashtag_names]
        relevant_tags = []
        for tag in suggested_tags:
            tag_lower = tag.lower()
            # Find matching hashtag (case-insensitive)
            for i, name in enumerate(hashtag_names_lower):
                if tag_lower == name:
                    relevant_tags.append(hashtag_names[i])  # Use original case
                    break
        
        return relevant_tags[:max_results]
    except Exception:
        logger.exception("Error determining relevant hashtags")
        return []

def generate_hashtags_with_trending(
    section: str | None,
    article_title: str | None = None,
    article_description: str | None = None,
    trending_hashtags: list[dict] | None = None
) -> list[str]:
    """
    Generates hashtags with pre-fetched trending hashtags (faster for batch operations).
    If trending_hashtags is None, uses cached trending hashtags.
    """
    hashtags = ["#MotherJones", "#Investigative"]
    
    # Add section-based hashtag
    if section:
        section_tag = f"#{section.replace(' ', '')}"
        hashtags.append(section_tag)
    
    # Use provided trending hashtags, or fall back to cached ones
    if trending_hashtags is None:
        trending_hashtags = get_cached_trending_hashtags()
    
    # Add relevant trending hashtags if article content is provided
    if article_title and article_description and trending_hashtags:
        try:
            relevant_trending = find_relevant_trending_hashtags(
                article_title, 
                article_description, 
                trending_hashtags,
                max_results=2  # Limit to avoid hashtag spam
            )
            hashtags.extend([f"#{tag}" for tag in relevant_trending])
        except Exception:
            logger.exception("Error processing trending hashtags")
            # Continue without trending hashtags if there's an error
    
    return hashtags

def generate_hashtags(
    section: str | None, 
    article_title: str | None = None, 
    article_description: str | None = None
) -> list[str]:
    """
    Generates hashtags based on the article's section and relevant trending hashtags.
    Uses cached trending hashtags (refreshed daily) and AI to determine relevance.
    """
    # Use the cached trending hashtags instead of fetching each time
    return generate_hashtags_with_trending(
        section=section,
        article_title=article_title,
        article_description=article_description,
        trending_hashtags=None  # Will use cached hashtags
    )

def generate_new_teaser(original_description: str, feedback_teaser: str, session: Session) -> str:
    """
    Generates a new teaser based on the original description and feedback from the current teaser,
    incorporating examples of previously approved teasers.
    """
    if not settings.google_api_key:
        logger.warning(
            "GOOGLE_API_KEY is not set. Falling back to simple concatenation for new teaser"
        )
        return f"New summary based on feedback: {feedback_teaser} (Fallback - {datetime.now().strftime('%H:%M:%S')})"

    try:
        # Retrieve a few recent approved examples
        statement = select(ApprovedTeaserExample).order_by(ApprovedTeaserExample.created_at.desc()).limit(3)
        approved_examples = session.exec(statement).all()

        prompt_examples = ""
        if approved_examples:
            prompt_examples = "Here are some examples of good teasers:\n\n"
            for example in approved_examples:
                prompt_examples += f"Original: {example.original_description[:150]}...\nApproved Teaser: {example.approved_teaser}\n\n"

        prompt = f"Given the original article content: \n\n{original_description}\n\nAnd the previous summary (feedback): \n\n{feedback_teaser}\n\n{prompt_examples}Generate a new, improved, concise, and engaging social media teaser. The new teaser should be ready to use, without any introductory phrases or options, and less than 200 characters."
        response = model.generate_content(prompt)
        return response.text
    except Exception:
        logger.exception("Error generating new teaser with AI")
        return f"New summary based on feedback: {feedback_teaser} (Error - {datetime.now().strftime('%H:%M:%S')})"
