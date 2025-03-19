import os
import re
import csv
import io
import uuid
import shutil
from datetime import datetime
from utils import FileUtils  # Removed OpenAI dependency
import gc

class DataProcessor:
    def __init__(self, session_id=None):
        """Initialize the data processor with a session directory."""
        self.base_dir = FileUtils.get_script_dir()
        self.session_id = session_id or self._generate_session_id()
        self.session_dir = os.path.join(self.base_dir, 'processing_sessions', self.session_id)
        self.invoice_data = {}  # Store data for multi-page invoices
        self._setup_session_directory()

    def _generate_session_id(self):
        """Generate a unique session ID using timestamp and UUID."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_id = str(uuid.uuid4())[:8]
        return f"session_{timestamp}_{unique_id}"

    def _setup_session_directory(self):
        """Create the session directory if it doesn't exist."""
        os.makedirs(self.session_dir, exist_ok=True)
        print(f"Created session directory: {self.session_dir}")

    @staticmethod
    def cleanup_sessions():
        """Clean up all processing session directories."""
        base_dir = FileUtils.get_script_dir()
        sessions_dir = os.path.join(base_dir, 'processing_sessions')
        if os.path.exists(sessions_dir):
            try:
                shutil.rmtree(sessions_dir)
                print("Cleaned up all processing sessions")
            except Exception as e:
                print(f"Error cleaning up sessions: {str(e)}")

if __name__ == "__main__":
    processor = DataProcessor()
    processor.process_all_files()