from datetime import datetime
import google.generativeai as genai
from app.config import settings

if settings.google_api_key:
    genai.configure(api_key=settings.google_api_key)
    model = genai.GenerativeModel('models/gemini-pro-latest')

def generate_teaser(description: str, max_length: int = 200) -> str:
    """
    Generates a teaser from the article description using a generative AI model.
    """
    if not settings.google_api_key:
        print("Warning: GOOGLE_API_KEY is not set. Falling back to simple truncation.")
        if len(description) <= max_length:
            return description
        return description[:max_length] + "..."

    try:
        prompt = f"Generate a super engaging, concise, and personal social media teaser for the following article. The teaser should be ready to use, without any introductory phrases or options, and less than {max_length} characters.\n\n{description}"
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Error generating teaser with AI: {e}")
        # Fallback to simple truncation
        if len(description) <= max_length:
            return description
        return description[:max_length] + "..."

def generate_hashtags(section: str | None) -> list[str]:
    """
    Generates hashtags based on the article's section.
    """
    hashtags = ["#MotherJones", "#Investigative"]
    if section:
        # Simple mapping for now, can be improved
        section_tag = f"#{section.replace(' ', '')}"
        hashtags.append(section_tag)
    return hashtags

def generate_new_teaser(original_description: str, feedback_teaser: str) -> str:
    """
    Generates a new teaser based on the original description and feedback from the current teaser.
    For now, this is a placeholder.
    """
    if not settings.google_api_key:
        print("Warning: GOOGLE_API_KEY is not set. Falling back to simple concatenation.")
        return f"New summary based on feedback: {feedback_teaser} (Fallback - {datetime.now().strftime('%H:%M:%S')})"

    try:
        prompt = f"Given the original article content: \n\n{original_description}\n\nAnd the previous summary (feedback): \n\n{feedback_teaser}\n\nGenerate a new, improved, concise, and engaging social media teaser. The new teaser should be ready to use, without any introductory phrases or options, and less than 200 characters."
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Error generating new teaser with AI: {e}")
        return f"New summary based on feedback: {feedback_teaser} (Error - {datetime.now().strftime('%H:%M:%S')})"
