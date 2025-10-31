import google.generativeai as genai
from app.config import settings

if settings.google_api_key:
    genai.configure(api_key=settings.google_api_key)
    model = genai.GenerativeModel('models/gemini-pro-latest')

def generate_teaser(description: str, max_length: int = 400) -> str:
    """
    Generates a teaser from the article description using a generative AI model.
    """
    if not settings.google_api_key:
        print("Warning: GOOGLE_API_KEY is not set. Falling back to simple truncation.")
        if len(description) <= max_length:
            return description
        return description[:max_length] + "..."

    try:
        prompt = f"Summarize the following article in a compelling and concise way, suitable for a social media teaser. The summary should be less than {max_length} characters:\n\n{description}"
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
