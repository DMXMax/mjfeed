from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    mastodon_access_token: str
    mastodon_instance_url: str
    rss_feeds: str = "https://www.motherjones.com/feed/"
    poll_interval: int = 86400 # 24 hours
    google_api_key: str = ""
    mastodon_post_visibility: str = "private"
    default_hashtags: str = "#MotherJones,#Investigative"

    class Config:
        env_file = ".env"

settings = Settings()
