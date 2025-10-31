from fastapi import FastAPI, Request, Depends, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from apscheduler.schedulers.background import BackgroundScheduler

from app.storage import Article, create_db_and_tables, engine
from app.rss_monitor import poll_feed
from app.mastodon_client import post_toot
from app.teaser import generate_hashtags
from app.config import settings

app = FastAPI()
templates = Jinja2Templates(directory="templates")
scheduler = BackgroundScheduler()

def get_session():
    with Session(engine) as session:
        yield session

@app.on_event("startup")
def on_startup():
    create_db_and_tables()
    poll_feed()
    scheduler.add_job(poll_feed, 'interval', seconds=settings.poll_interval)
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
    return templates.TemplateResponse("review.html", {"request": request, "articles": articles})



@app.post("/process_article/{article_id}")
def process_article(
    article_id: int,
    action: str = Form(...),
    edited_teaser: str = Form(...),
    session: Session = Depends(get_session)
):
    article = session.get(Article, article_id)
    if not article:
        return {"message": "Article not found"}

    if action == "approve":
        article.ai_teaser = edited_teaser
        article.status = "approved"
        session.add(article)
        session.commit()
        return {"message": "Article approved and teaser updated"}
    elif action == "discard":
        article.status = "discarded"
        session.add(article)
        session.commit()
        return {"message": "Article discarded"}
    return {"message": "Invalid action"}

def post_approved_articles():
    with Session(engine) as session:
        statement = select(Article).where(Article.status == "approved")
        articles_to_post = session.exec(statement).all()
        for article in articles_to_post:
            teaser = article.ai_teaser
            hashtags = generate_hashtags(None) # Placeholder for section
            content = f"{article.title}\n\n{teaser}\n\nRead more → {article.link}\n\n{' '.join(hashtags)}"            
            status = post_toot(content, visibility=settings.mastodon_post_visibility)
            if status:
                article.status = "posted"
                session.add(article)
                session.commit()
