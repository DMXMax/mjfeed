from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    mastodon_access_token: str
    mastodon_instance_url: str
    rss_feeds: str = "https://www.motherjones.com/feed/"
    poll_interval: int = 1800 # 30 minutes
    google_api_key: str = ""
    default_hashtags: str = "#MotherJones,#Investigative"

    class Config:
        env_file = ".env"

settings = Settings()
