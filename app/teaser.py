from datetime import datetime, timedelta
import google.generativeai as genai
from sqlmodel import Session, select
from app.config import settings
from app.storage import ApprovedTeaserExample
from app.mastodon_client import get_trending_hashtags

# Use a cheaper / faster default model, overridable via environment variable
DEFAULT_GOOGLE_MODEL = "models/gemini-2.5-flash-lite"
MODEL_NAME = getattr(settings, "google_model_name", DEFAULT_GOOGLE_MODEL)

if settings.google_api_key:
    genai.configure(api_key=settings.google_api_key)
    model = genai.GenerativeModel(MODEL_NAME)

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
        print("Fetching trending hashtags from Mastodon...")
        trending = get_trending_hashtags(limit=20)
        _trending_hashtags_cache = trending
        _trending_hashtags_cache_time = datetime.utcnow()
        print(f"Successfully cached {len(trending)} trending hashtags")
        return trending
    except Exception as e:
        print(f"Error fetching trending hashtags: {e}")
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

def generate_teaser(description: str, max_length: int = 200) -> str:
    """
    Generates a teaser from the article description using a generative AI model.
    """
    if not settings.google_api_key:
        print("Warning: GOOGLE_API_KEY is not set. Falling back to simple truncation.")
        if len(description) <= max_length:
            return description
        return description[:max_length] + "..."

    try:
        prompt = f"Generate a super engaging, concise, and personal social media teaser for the following article. The teaser should be ready to use, without any introductory phrases or options, and less than {max_length} characters.\n\n{description}"
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Error generating teaser with AI: {e}")
        # Fallback to simple truncation
        if len(description) <= max_length:
            return description
        return description[:max_length] + "..."

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
    except Exception as e:
        print(f"Error determining relevant hashtags: {e}")
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
        except Exception as e:
            print(f"Error processing trending hashtags: {e}")
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
        print("Warning: GOOGLE_API_KEY is not set. Falling back to simple concatenation.")
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
    except Exception as e:
        print(f"Error generating new teaser with AI: {e}")
        return f"New summary based on feedback: {feedback_teaser} (Error - {datetime.now().strftime('%H:%M:%S')})"
