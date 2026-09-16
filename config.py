import os

from dotenv import load_dotenv


load_dotenv()


GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GEMINI_JUDGE_MODEL = "gemini-3.5-flash-lite"


if not GOOGLE_API_KEY:
    raise RuntimeError(
        "GOOGLE_API_KEY is missing. "
        "Add it to the .env file in the project root."
    )
