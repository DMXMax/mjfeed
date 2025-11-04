from sqlmodel import Field, SQLModel, create_engine
from datetime import datetime
from typing import Optional

class Article(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    guid: str = Field(unique=True, index=True)
    title: str
    link: str
    pub_date: datetime
    description: str
    author: Optional[str] = None
    ai_teaser: Optional[str] = None
    article_length: Optional[int] = None
    status: str = Field(default="pending") # pending, approved, posted
    visibility: str = Field(default="private") # public, private, direct
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


DATABASE_URL = "sqlite:///database.db"
engine = create_engine(DATABASE_URL, echo=True)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
