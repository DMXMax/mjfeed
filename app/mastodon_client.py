import logging

from mastodon import Mastodon

from app.config import settings


logger = logging.getLogger(__name__)

def get_mastodon_client():
    """
    Initializes and returns a Mastodon API client.
    """
    mastodon = Mastodon(
        access_token=settings.mastodon_access_token,
        api_base_url=settings.mastodon_instance_url
    )
    return mastodon

def post_toot(content: str, visibility: str = "public") -> bool:
    mastodon = get_mastodon_client()
    try:
        status_object = mastodon.status_post(content, visibility=visibility)
        logger.info(
            "Toot posted successfully",
            extra={
                "visibility": visibility,
                "status_id": getattr(status_object, "id", None),
            },
        )
        return True
    except Exception:
        logger.exception("Error posting toot")
        return False

def get_trending_hashtags(limit: int = 20) -> list[dict]:
    """
    Fetches trending hashtags from the Mastodon instance.
    Returns a list of hashtag dictionaries with 'name' and 'history' fields.
    """
    mastodon = get_mastodon_client()
    try:
        trends = mastodon.trending_tags(limit=limit)
        return trends
    except Exception:
        logger.exception("Error fetching trending hashtags")
        return []
