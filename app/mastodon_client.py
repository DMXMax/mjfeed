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

def post_toot(content: str):
    """
    Posts a toot to Mastodon.
    """
    mastodon = get_mastodon_client()
    try:
        status = mastodon.status_post(content)
        return status
    except Exception as e:
        print(f"Error posting to Mastodon: {e}")
        return None
