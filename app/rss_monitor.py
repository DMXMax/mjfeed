import html
import logging
from datetime import datetime

import feedparser
import requests
from bs4 import BeautifulSoup
from sqlmodel import Session, select

from app.storage import Article, engine
from app.teaser import generate_teaser, generate_hashtags

logger = logging.getLogger(__name__)

RSS_URL = "https://www.motherjones.com/feed/"

def poll_feed():
    logger.info("Polling RSS feed using requests", extra={"rss_url": RSS_URL})
    try:
        response = requests.get(
            RSS_URL,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        logger.info(
            "RSS fetch completed",
            extra={"status_code": response.status_code},
        )
        if response.status_code == 200:
            feed = feedparser.parse(response.content)
        else:
            logger.warning(
                "Failed to fetch RSS feed",
                extra={"status_code": response.status_code},
            )
            return
    except requests.exceptions.RequestException:
        logger.exception("An error occurred during the RSS request")
        return

    logger.info(
        "Parsed RSS feed entries",
        extra={"entry_count": len(feed.entries)},
    )
    
    with Session(engine) as session:
        # Get all guids from the feed
        feed_guids = {entry.id for entry in feed.entries}
        
        # Get all guids from the database
        db_guids = set(session.exec(select(Article.guid)).all())
        
        # Find guids to delete
        guids_to_delete = db_guids - feed_guids
        
        if guids_to_delete:
            logger.info(
                "Found articles to delete",
                extra={"delete_count": len(guids_to_delete)},
            )
            statement = select(Article).where(Article.guid.in_(guids_to_delete))
            articles_to_delete = session.exec(statement).all()
            for article in articles_to_delete:
                session.delete(article)
            session.commit()

        for entry in feed.entries:
            logger.info(
                "Processing feed entry",
                extra={"title": entry.title, "guid": getattr(entry, "id", None)},
            )
            # Check if article exists
            statement = select(Article).where(Article.guid == entry.id)
            existing_article = session.exec(statement).first()

            if not existing_article:
                logger.info(
                    "New article detected, adding to database",
                    extra={"guid": entry.id},
                )
                clean_description = html.unescape(entry.summary)
                clean_title = html.unescape(entry.title)

                full_text = ""
                if hasattr(entry, 'content') and entry.content:
                    soup = BeautifulSoup(entry.content[0].value, 'html.parser')
                    full_text = soup.get_text(separator=' ', strip=True)
                
                article_len = len(full_text) if full_text else 0

                teaser = generate_teaser(full_text if full_text else clean_description)
                # Generate suggested hashtags and store them
                hashtags = generate_hashtags(
                    section=None,
                    article_title=clean_title,
                    article_description=clean_description
                )
                hashtags_str = ','.join(hashtags) if hashtags else None
                
                article = Article(
                    guid=entry.id,
                    title=clean_title,
                    link=entry.link,
                    pub_date=datetime(*entry.published_parsed[:6]),
                    description=clean_description,
                    author=entry.author if 'author' in entry else None,
                    ai_teaser=teaser,
                    article_length=article_len,
                    suggested_hashtags=hashtags_str,
                )
                session.add(article)
            else:
                logger.info(
                    "Article already exists, skipping",
                    extra={"guid": entry.id},
                )
        logger.info("Committing RSS changes to the database")
        session.commit()
    logger.info("Finished polling RSS feed")
