import feedparser
from sqlmodel import Session, select
from app.storage import Article, engine
from app.teaser import generate_teaser
from datetime import datetime
import requests
import html
from bs4 import BeautifulSoup

RSS_URL = "https://www.motherjones.com/feed/"

def poll_feed():
    print("Polling RSS feed using requests...")
    try:
        response = requests.get(RSS_URL, headers={'User-Agent': 'Mozilla/5.0'})
        print(f"HTTP Status Code: {response.status_code}")
        if response.status_code == 200:
            feed = feedparser.parse(response.content)
        else:
            print(f"Failed to fetch feed. Status code: {response.status_code}")
            return
    except requests.exceptions.RequestException as e:
        print(f"An error occurred during the request: {e}")
        return

    print(f"Found {len(feed.entries)} entries in the feed.")
    
    with Session(engine) as session:
        # Get all guids from the feed
        feed_guids = {entry.id for entry in feed.entries}
        
        # Get all guids from the database
        db_guids = set(session.exec(select(Article.guid)).all())
        
        # Find guids to delete
        guids_to_delete = db_guids - feed_guids
        
        if guids_to_delete:
            print(f"Found {len(guids_to_delete)} articles to delete.")
            statement = select(Article).where(Article.guid.in_(guids_to_delete))
            articles_to_delete = session.exec(statement).all()
            for article in articles_to_delete:
                session.delete(article)
            session.commit()

        for entry in feed.entries:
            print(f"Processing entry: {entry.title}")
            # Check if article exists
            statement = select(Article).where(Article.guid == entry.id)
            existing_article = session.exec(statement).first()

            if not existing_article:
                print(f"  -> New article. Adding to database.")
                clean_description = html.unescape(entry.summary)
                clean_title = html.unescape(entry.title)

                full_text = ""
                if hasattr(entry, 'content') and entry.content:
                    soup = BeautifulSoup(entry.content[0].value, 'html.parser')
                    full_text = soup.get_text(separator=' ', strip=True)
                
                article_len = len(full_text) if full_text else 0

                teaser = generate_teaser(full_text if full_text else clean_description)
                article = Article(
                    guid=entry.id,
                    title=clean_title,
                    link=entry.link,
                    pub_date=datetime(*entry.published_parsed[:6]),
                    description=clean_description,
                    author=entry.author if 'author' in entry else None,
                    ai_teaser=teaser,
                    article_length=article_len,
                )
                session.add(article)
            else:
                print(f"  -> Article already exists. Skipping.")
        print("Committing changes to the database.")
        session.commit()
    print("Finished polling feed.")
