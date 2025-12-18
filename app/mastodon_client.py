from mastodon import Mastodon
from app.config import settings

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
        print(f"Toot posted successfully with visibility: {visibility}!")
        print(f"Mastodon Status Object: {status_object}")
        return True
    except Exception as e:
        print(f"Error posting toot: {e}")
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
    except Exception as e:
        print(f"Error fetching trending hashtags: {e}")
        return []
