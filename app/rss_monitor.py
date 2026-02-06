import html
import logging
import re
from datetime import datetime

import feedparser
import requests
from bs4 import BeautifulSoup
from sqlmodel import Session, select

from app.storage import Article, engine
from app.teaser import generate_hashtags

logger = logging.getLogger(__name__)

RSS_URL = "https://www.motherjones.com/feed/"


def _clean_text(raw_html: str | None) -> str:
    """
    Normalize RSS snippets by stripping tags, decoding entities, and collapsing spaces.
    """
    if not raw_html:
        return ""
    text = BeautifulSoup(raw_html, "html.parser").get_text(separator=" ", strip=True)
    text = html.unescape(text)
    # Collapse repeated whitespace/newlines to single spaces
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_full_text(entry) -> str:
    """
    Extracts combined cleaned content blocks from feed entry.
    Prefer <content:encoded> if present; fall back to feedparser's content array.
    """
    raw_blocks: list[str] = []

    # Feedparser exposes <content:encoded> via entry.content (list of dicts)
    if hasattr(entry, "content") and entry.content:
        for part in entry.content:
            value = getattr(part, "value", None)
            if value is None and isinstance(part, dict):
                value = part.get("value")
            if value:
                raw_blocks.append(value)

    # Some feeds expose raw strings via entry["content:encoded"] or entry.content_encoded
    encoded_raw = getattr(entry, "content_encoded", None)
    if encoded_raw is None:
        try:
            encoded_raw = entry.get("content:encoded")
        except AttributeError:
            encoded_raw = None
    if encoded_raw:
        if isinstance(encoded_raw, list):
            raw_blocks.extend([block for block in encoded_raw if isinstance(block, str) and block])
        elif isinstance(encoded_raw, str):
            raw_blocks.append(encoded_raw)

    if not raw_blocks:
        return ""
    combined = " ".join(raw_blocks)
    return _clean_text(combined)

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
                clean_description = _clean_text(getattr(entry, "summary", ""))
                clean_title = _clean_text(entry.title)

                full_text = _extract_full_text(entry)
                article_len = len(full_text) if full_text else 0

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
                    ai_teaser=None,  # Summary will be generated on-demand
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
