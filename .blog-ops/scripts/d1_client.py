#!/usr/bin/env python3
"""
D1 REST API client for blog state management.

Uses the REST API at data.klinux.dpdns.org with Bearer token auth.
State is stored in the shared 'state' table with key 'blog_state',
sharing the ocean database with the whispers project.
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta


# Beijing timezone
TZ_BEIJING = timezone(timedelta(hours=8))

# State key in the shared state table
STATE_KEY = "blog_state"


class D1Client:
    """D1 REST API client for blog state management."""

    def __init__(self, api_url=None, api_key=None):
        self.api_url = (api_url or os.environ.get("D1_API_URL", "")).rstrip("/")
        self.api_key = api_key or os.environ.get("D1_API_KEY", "")

        if not self.api_url or not self.api_key:
            raise ValueError("D1Client requires D1_API_URL and D1_API_KEY")

    def _query(self, sql, params=None):
        """Execute a SQL query via the REST API."""
        url = f"{self.api_url}/query"
        payload = {"query": sql, "params": params or []}

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "BlogRunner/1.0")

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))

            if not result.get("success", True) and "error" in result:
                raise RuntimeError(f"D1 query error: {result['error']}")

            return result.get("results", [])
        except urllib.error.URLError as e:
            raise RuntimeError(f"D1 request failed: {e}")

    # ==================== State Management ====================

    def get_state(self):
        """
        Read the blog state from D1.
        Returns a dict with last_run, week_start, weekly_count, stats.
        Returns empty state if not found.
        """
        results = self._query(
            "SELECT value FROM state WHERE key = ?;",
            [STATE_KEY]
        )

        if not results:
            return self._default_state()

        row = results[0]
        value_str = row.get("value", "{}") if isinstance(row, dict) else "{}"

        try:
            return json.loads(value_str)
        except json.JSONDecodeError:
            print("Warning: state JSON parse failed, returning default", file=sys.stderr)
            return self._default_state()

    def save_state(self, state):
        """Save the blog state to D1 using UPSERT."""
        value_str = json.dumps(state, ensure_ascii=False)
        now_str = datetime.now(TZ_BEIJING).strftime("%Y-%m-%d %H:%M:%S")

        self._query(
            "INSERT INTO state (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?;",
            [STATE_KEY, value_str, now_str, value_str, now_str]
        )

    def _default_state(self):
        """Return a default empty state."""
        return {
            "last_run": "",
            "week_start": "",
            "weekly_count": 0,
            "stats": {
                "total_published": 0,
            }
        }


# ==================== CLI for testing ====================

if __name__ == "__main__":
    client = D1Client()

    print("=== Current Blog State ===")
    state = client.get_state()
    print(json.dumps(state, ensure_ascii=False, indent=2))
