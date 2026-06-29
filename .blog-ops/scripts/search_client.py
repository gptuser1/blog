#!/usr/bin/env python3
"""
Tavily search client.

Provides two search modes:
  - search_trending: fast news search for topic discovery (basic depth)
  - search_deep: advanced search with raw content for writing material

API docs: https://docs.tavily.com/documentation/api-reference/endpoint/search
Endpoint: POST https://api.tavily.com/search
Auth: Bearer token

Usage:
    from search_client import TavilyClient
    client = TavilyClient(api_key="...")
    results = client.search_trending("AI 行业动态")
    results = client.search_deep("灵晟超算登顶 TOP500")
"""

import json
import os
import sys
import requests


class TavilyClient:
    """Tavily Search API client."""

    BASE_URL = "https://api.tavily.com/search"

    def __init__(self, api_key=None):
        self.api_key = api_key or os.environ.get("TAVILY_API_KEY", "")
        if not self.api_key:
            raise ValueError("TavilyClient requires TAVILY_API_KEY")

    def _search(self, query, search_depth="basic", topic="general",
                max_results=5, time_range=None, include_answer=True,
                include_raw_content=False, include_images=False):
        """Execute a Tavily search request."""
        payload = {
            "query": query,
            "search_depth": search_depth,
            "topic": topic,
            "max_results": max_results,
            "include_answer": include_answer,
            "include_raw_content": include_raw_content,
            "include_images": include_images,
        }
        if time_range:
            payload["time_range"] = time_range

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            resp = requests.post(self.BASE_URL, json=payload, headers=headers, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Tavily request failed: {e}")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Tavily response parse failed: {e}")

    def search_trending(self, query, max_results=8, time_range="week"):
        """
        Fast news search for topic discovery.

        Uses basic depth + news topic for speed and low cost.
        Returns dict with 'answer', 'results' (list of {title, url, content, score}).
        """
        return self._search(
            query=query,
            search_depth="basic",
            topic="news",
            max_results=max_results,
            time_range=time_range,
            include_answer=True,
            include_raw_content=False,
            include_images=False,
        )

    def search_deep(self, query, max_results=5):
        """
        Deep search for writing material.

        Uses advanced depth with raw content for rich context.
        Returns dict with 'answer', 'results' (list with 'raw_content').
        """
        return self._search(
            query=query,
            search_depth="advanced",
            topic="general",
            max_results=max_results,
            time_range=None,
            include_answer=True,
            include_raw_content=True,
            include_images=False,
        )

    def search_images(self, query, max_results=5):
        """
        Search for images related to a query.

        Returns list of image dicts: [{"url": "...", "description": "..."}, ...].
        """
        result = self._search(
            query=query,
            search_depth="basic",
            topic="general",
            max_results=max_results,
            time_range=None,
            include_answer=False,
            include_raw_content=False,
            include_images=True,
        )
        return result.get("images", [])


# ==================== CLI for testing ====================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Tavily search client test")
    parser.add_argument("--mode", choices=["trending", "deep", "images"],
                        default="trending")
    parser.add_argument("--query", required=True)
    parser.add_argument("--max-results", type=int, default=5)
    args = parser.parse_args()

    client = TavilyClient()

    if args.mode == "trending":
        result = client.search_trending(args.query, max_results=args.max_results)
        print(f"Answer: {result.get('answer', '(none)')}")
        print(f"\nResults ({len(result.get('results', []))} items):")
        for r in result.get("results", []):
            print(f"  [{r.get('score', 0):.2f}] {r.get('title', '')}")
            print(f"        {r.get('url', '')}")
            print(f"        {r.get('content', '')[:120]}...")
    elif args.mode == "deep":
        result = client.search_deep(args.query, max_results=args.max_results)
        print(f"Answer: {result.get('answer', '(none)')}")
        print(f"\nResults ({len(result.get('results', []))} items):")
        for r in result.get("results", []):
            raw_len = len(r.get("raw_content") or "")
            print(f"  [{r.get('score', 0):.2f}] {r.get('title', '')}")
            print(f"        {r.get('url', '')}")
            print(f"        content: {len(r.get('content', ''))} chars, raw: {raw_len} chars")
    elif args.mode == "images":
        images = client.search_images(args.query, max_results=args.max_results)
        print(f"Images ({len(images)} items):")
        for img in images:
            print(f"  {img.get('url', '')}")
            print(f"    {img.get('description', '')}")
