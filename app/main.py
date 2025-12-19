import logging

from fastapi import FastAPI, Request, Depends, Form
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from apscheduler.schedulers.background import BackgroundScheduler

from app.storage import Article, ApprovedTeaserExample, create_db_and_tables, engine
from app.rss_monitor import poll_feed
from app.mastodon_client import post_toot
from app.teaser import generate_hashtags, generate_new_teaser, fetch_and_cache_trending_hashtags
from app.config import settings
from app.logging_config import configure_logging


configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")
scheduler = BackgroundScheduler()

def get_session():
    with Session(engine) as session:
        yield session

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("static/favicon.svg")

@app.on_event("startup")
def on_startup():
    create_db_and_tables()
    fetch_and_cache_trending_hashtags()  # Fetch trending hashtags FIRST, before polling feed
    poll_feed()  # Now articles will have trending hashtags available
    scheduler.add_job(poll_feed, 'interval', seconds=settings.poll_interval)
    scheduler.add_job(fetch_and_cache_trending_hashtags, 'interval', seconds=settings.poll_interval)  # Fetch trending hashtags daily
    scheduler.add_job(post_approved_articles, 'interval', seconds=60)
    scheduler.start()

@app.on_event("shutdown")
def on_shutdown():
    scheduler.shutdown()

@app.get("/", response_class=HTMLResponse)
def read_root():
    return """
    <html>
        <head>
            <title>Mother Jones RSS to Mastodon Scheduler</title>
        </head>
        <body>
            <h1>Mother Jones RSS to Mastodon Scheduler</h1>
            <a href="/review">Review Articles</a>
        </body>
    </html>
    """

@app.get("/review", response_class=HTMLResponse)
def review_articles(request: Request, session: Session = Depends(get_session)):
    statement = select(Article).where(Article.status == "pending")
    articles = session.exec(statement).all()
    # Use stored suggested hashtags, but regenerate if only basic ones exist
    articles_with_hashtags = []
    for article in articles:
        # Parse stored hashtags
        if article.suggested_hashtags:
            stored_hashtags = article.suggested_hashtags.split(',')
            # If only basic hashtags, regenerate with trending hashtags
            if len(stored_hashtags) <= 2 and all(
                tag in ["#MotherJones", "#Investigative"] for tag in stored_hashtags
            ):
                # Regenerate hashtags with trending ones
                try:
                    suggested_hashtags = generate_hashtags(
                        section=None,
                        article_title=article.title,
                        article_description=article.description
                    )
                    # Update stored hashtags
                    article.suggested_hashtags = ','.join(suggested_hashtags)
                    session.add(article)
                    session.commit()
                except Exception:
                    logger.exception(
                        "Error regenerating hashtags for article",
                        extra={"article_id": article.id},
                    )
                    suggested_hashtags = stored_hashtags
            else:
                suggested_hashtags = stored_hashtags
        else:
            # No stored hashtags, generate them
            try:
                suggested_hashtags = generate_hashtags(
                    section=None,
                    article_title=article.title,
                    article_description=article.description
                )
                # Store them
                article.suggested_hashtags = ','.join(suggested_hashtags)
                session.add(article)
                session.commit()
            except Exception:
                logger.exception(
                    "Error generating hashtags for article",
                    extra={"article_id": article.id},
                )
                suggested_hashtags = ["#MotherJones", "#Investigative"]
        
        articles_with_hashtags.append({
            "article": article,
            "suggested_hashtags": suggested_hashtags
        })
    return templates.TemplateResponse("review.html", {"request": request, "articles_with_hashtags": articles_with_hashtags})



@app.post("/process_article/{article_id}")
def process_article(
    article_id: int,
    action: str = Form(...),
    edited_teaser: str = Form(...),
    visibility: str = Form(...),
    session: Session = Depends(get_session)
):
    article = session.get(Article, article_id)
    if not article:
        return {"message": "Article not found"}

    if action == "approve":
        # Validate visibility value
        valid_visibilities = ["public", "unlisted", "private", "direct"]
        if visibility not in valid_visibilities:
            return {"message": f"Invalid visibility value: {visibility}. Must be one of {valid_visibilities}"}
        
        article.ai_teaser = edited_teaser
        article.status = "approved"
        article.visibility = visibility
        session.add(article)

        approved_example = ApprovedTeaserExample(
            original_article_id=article.id,
            original_description=article.description,
            approved_teaser=edited_teaser
        )
        session.add(approved_example)
        session.commit()
        session.refresh(article)
        session.refresh(approved_example)
        return {"message": f"Article approved with visibility: {visibility}"}
    elif action == "discard":
        article.status = "discarded"
        session.add(article)
        session.commit()
        return {"message": "Article discarded"}
    elif action == "re_summarize":
        # Assuming article.description holds the original article content
        new_teaser = generate_new_teaser(article.description, edited_teaser, session)
        article.ai_teaser = new_teaser
        session.add(article)
        session.commit()
        return {"message": "Article re-summarized", "new_teaser": new_teaser}
    return {"message": "Invalid action"}

def post_approved_articles():
    with Session(engine) as session:
        statement = select(Article).where(Article.status == "approved")
        articles_to_post = session.exec(statement).all()
        for article in articles_to_post:
                        teaser = article.ai_teaser
                        # Use stored hashtags, or generate if not stored (for older articles)
                        if article.suggested_hashtags:
                            hashtags = article.suggested_hashtags.split(',')
                        else:
                            hashtags = generate_hashtags(
                                section=None,
                                article_title=article.title,
                                article_description=article.description
                            )
                        # Construct the content for the Mastodon toot
                        content = f"{teaser}\n\nRead more → {article.link}\n\n{' '.join(hashtags)}"
                        
                        mastodon_visibility = article.visibility
                        if mastodon_visibility == "direct":
                            content += " @bullfinch"
                            mastodon_visibility = "direct"
            
                        status = post_toot(content, visibility=mastodon_visibility)
                        if status:
                            article.status = "posted"
                            session.add(article)
                            session.commit()
