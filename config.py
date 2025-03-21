import os
import platform
from dotenv import load_dotenv

# OpenAI Configuration
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# print(OPENAI_API_KEY)

# Poppler Configuration
if platform.system() == "Windows":
    POPPLER_PATH = "C:\\Program Files\\poppler\\bin"
else:
    # On Linux, poppler-utils is installed via apt-get and is usually in PATH
    POPPLER_PATH = None  # or '/usr/bin' if your code requires an explicit path

# File Processing
OUTPUT_CSV_NAME = "order_data.csv"

# Models
OPENAI_MODEL = "gpt-4-turbo"

# Animation Settings
TYPING_DELAY = 0.03
LOADING_ANIMATION_CHARS = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"] 