import os
import platform
import shutil
import sys
import time
from subprocess import Popen, PIPE
import openai
from config import OPENAI_API_KEY, POPPLER_PATH, TYPING_DELAY, LOADING_ANIMATION_CHARS

# OpenAI setup
openai.api_key = OPENAI_API_KEY
client = openai.OpenAI(api_key=openai.api_key)

class FileUtils:
    @staticmethod
    def get_txt_files(directory):
        """Get all TXT files in the specified directory."""
        return [f for f in os.listdir(directory) if f.endswith('.txt')]

    @staticmethod
    def get_pdf_files(directory):
        """Get all PDF files in the specified directory."""
        return [f for f in os.listdir(directory) if f.lower().endswith('.pdf')]

    @staticmethod
    def get_script_dir():
        """Get the directory where the current script is located."""
        return os.path.dirname(os.path.abspath(__file__))
