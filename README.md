# Mother Jones RSS to Mastodon Scheduler

This project is a curated automation system that monitors Mother Jones RSS feeds, generates short Mastodon-formatted teasers, and allows a human reviewer to approve and schedule posts before they are published.

## Features

- Monitors one or more Mother Jones RSS feeds.
- Detects new stories and stores them in a database.
- Generates short teasers and relevant hashtags for Mastodon posts.
- Provides a web-based UI for reviewing, approving, and discarding articles.
- Schedules and posts approved articles to Mastodon.

## Project Structure

```
motherjones-masto/
├── app/
│   ├── main.py
│   ├── rss_monitor.py
│   ├── teaser.py
│   ├── review_ui.py
│   ├── mastodon_client.py
│   ├── storage.py
│   └── config.py
├── templates/review.html
├── .env
├── requirements.txt
├── docker-compose.yml
└── README.md
```

## Getting Started

### Prerequisites

- Python 3.12+
- `uv` package manager

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/your-username/motherjones-masto.git
   cd motherjones-masto
   ```

2. Install the dependencies:
   ```bash
   uv pip install -r requirements.txt
   ```

3. Create a `.env` file and add your Mastodon API credentials:
   ```
   MASTODON_ACCESS_TOKEN="your_access_token"
   MASTODON_INSTANCE_URL="https://your_mastodon_instance.com"
   ```

### Running the Application

1. Run the FastAPI application:
   ```bash
   uvicorn app.main:app --reload
   ```

2. Open your browser and go to `http://127.0.0.1:8000`.

## Workflow

1. The `rss_monitor.py` script polls the RSS feed every 30 minutes (configurable).
2. New articles are added to the database with a "pending" status.
3. Go to the `/review` page to see the list of pending articles.
4. You can approve or discard each article.
5. Approved articles will be posted to Mastodon by the scheduler.

