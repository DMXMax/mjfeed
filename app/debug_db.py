
from sqlmodel import Session, select
from app.storage import Article, engine

def debug_db():
    with Session(engine) as session:
        statement = select(Article)
        articles = session.exec(statement).all()
        if not articles:
            print("No articles found in the database.")
        for article in articles:
            print(f"ID: {article.id}, Status: {article.status}, Title: {article.title}")

if __name__ == "__main__":
    debug_db()
