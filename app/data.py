"""
File-reading functions for the Northstar Services IT Service Desk API.

These functions only know how to read JSON files from disk. They do not
know anything about HTTP, FastAPI, or business rules. Keeping them
separate makes each piece easy to test and easy to explain on its own.
"""

import json
from pathlib import Path

# The "data" folder that sits next to the "app" folder, at the project root.
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def load_json_file(filename: str):
    """Read one JSON file from the data/ folder and return its contents."""
    file_path = DATA_DIR / filename
    with open(file_path, "r", encoding="utf-8") as file:
        return json.load(file)


def load_employees() -> list[dict]:
    """Return the list of synthetic employees."""
    return load_json_file("employees.json")


def load_tickets() -> list[dict]:
    """Return the list of synthetic VPN help desk tickets."""
    return load_json_file("tickets.json")


def load_service_status() -> dict:
    """Return the current synthetic VPN service status."""
    return load_json_file("service_status.json")
