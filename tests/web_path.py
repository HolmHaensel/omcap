"""Shared path of the page under test (one constant instead of a copy per test file)."""
from pathlib import Path

HTML_PATH = Path(__file__).resolve().parent.parent / "omcap" / "web" / "index.html"
