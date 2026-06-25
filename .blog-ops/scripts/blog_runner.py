#!/usr/bin/env python3
"""
Blog runner - main orchestration script.

Executed by GitHub Actions on a daily cron schedule.
Handles:
1. Check if today should publish (rhythm control: weekly min 2, checkpoints)
2. Pick a topic (pool 70% / Tavily search 30%)
3. Deep search for writing material via Tavily
4. Generate article via AI (DeepSeek-V4-Flash, thinking disabled)
5. Images: Tavily search first, AI generation (CF Workers AI) as fallback
6. Create post, lint, update publish-log
7. Git commit and push
8. Update D1 state

Usage:
    python .blog-ops/scripts/blog_runner.py [--dry-run] [--force]
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import random
import urllib.request
import urllib.error
import uuid
from datetime import datetime, timezone, timedelta

# Add scripts directory to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from ai_client import create_text_provider, merge_usage_into_state
from d1_client import D1Client
from search_client import TavilyClient

# Paths
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
CONFIG_PATH = os.path.join(PROJECT_ROOT, ".blog-ops", "config.json")
PUBLISH_LOG_PATH = os.path.join(PROJECT_ROOT, ".blog-ops", "publish-log.md")
TOPICS_PATH = os.path.join(PROJECT_ROOT, ".blog-ops", "topics.md")
POSTS_DIR = os.path.join(PROJECT_ROOT, "content", "posts")
IMAGES_DIR = os.path.join(PROJECT_ROOT, "static", "images")

# Beijing timezone
TZ_BEIJING = timezone(timedelta(hours=8))


def now_beijing():
    """Get current Beijing time."""
    return datetime.now(TZ_BEIJING)


def load_json(path):
    """Load a JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_script(cmd, cwd=PROJECT_ROOT):
    """Run a subprocess and return stdout and return code."""
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Command failed: {' '.join(cmd)}", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
    return result.stdout, result.returncode


# ==================== Rhythm Control ====================

def get_week_monday(now_dt):
    """Get the Monday date of the current week (Beijing time)."""
    monday = now_dt - timedelta(days=now_dt.weekday())
    return monday.strftime("%Y-%m-%d")


def should_publish(state, now_dt, config):
    """
    Decide if today should publish based on weekly rhythm.

    Rules:
    - Wednesday checkpoint: if weekly_count == 0, must publish
    - Saturday checkpoint: if weekly_count < weekly_min, must publish
    - Other days: probabilistic, targeting weekly_target
    - Never exceed weekly_target + 1
    """
    weekly_min = config.get("schedule", {}).get("weekly_min", 2)
    weekly_target = config.get("schedule", {}).get("weekly_target", 3)
    wed_ckpt = config.get("schedule", {}).get("wednesday_checkpoint", True)
    sat_ckpt = config.get("schedule", {}).get("saturday_checkpoint", True)

    week_start = get_week_monday(now_dt)

    # Reset weekly count if new week
    if state.get("week_start") != week_start:
        state["week_start"] = week_start
        state["weekly_count"] = 0

    weekly_count = state.get("weekly_count", 0)

    # Already met target, skip
    if weekly_count >= weekly_target + 1:
        return False, "weekly target already exceeded"

    weekday = now_dt.weekday()  # 0=Monday, 6=Sunday

    # Wednesday checkpoint
    if weekday == 2 and wed_ckpt and weekly_count == 0:
        return True, "Wednesday checkpoint: 0 posts this week"

    # Saturday checkpoint
    if weekday == 5 and sat_ckpt and weekly_count < weekly_min:
        return True, f"Saturday checkpoint: only {weekly_count} posts (min {weekly_min})"

    # Other days: probabilistic
    # Higher chance if behind schedule
    if weekly_count < weekly_min:
        prob = 0.6  # behind schedule, high chance
    elif weekly_count < weekly_target:
        prob = 0.35  # on track, moderate chance
    else:
        prob = 0.1  # met target, low chance

    if random.random() < prob:
        return True, f"probabilistic trigger (p={prob}, count={weekly_count})"

    return False, f"not triggered (p={prob}, count={weekly_count})"


# ==================== Topic Selection ====================

def pick_topic_from_pool():
    """Run pick_topic.py to select from topic pool or get search instruction.
    Uses --no-remove so the topic is only removed after successful publish.
    """
    stdout, rc = run_script([
        sys.executable,
        os.path.join(SCRIPT_DIR, "pick_topic.py"),
        "--no-remove",
    ])

    if rc != 0:
        return "search", "请搜索近期实时热点和新闻，选择一个值得写的话题。"

    lines = stdout.strip().split("\n")
    result_type = None
    content = ""
    for line in lines:
        if line.startswith("RESULT: "):
            result_type = line[8:].strip()
        elif line.startswith("TOPIC: "):
            content = line[7:].strip()
        elif line.startswith("INSTRUCTION: "):
            content = line[13:].strip()

    if result_type == "pool" and content:
        return "pool", content
    return "search", content or "请搜索近期实时热点和新闻，选择一个值得写的话题。"


def remove_topic_from_pool(topic):
    """Remove a topic from the pool after successful publish.
    Calls pick_topic.py's removal logic via a direct import to avoid
    spawning a subprocess just for deletion.
    """
    try:
        sys.path.insert(0, SCRIPT_DIR)
        import pick_topic as pt
        removed = pt.remove_topic_from_pool(topic, TOPICS_PATH)
        if removed:
            print(f"Topic removed from pool: {topic}")
        return removed
    except Exception as e:
        print(f"Warning: failed to remove topic from pool: {e}", file=sys.stderr)
        return False


def get_recent_titles(count=3):
    """Get recent article titles from publish-log.md."""
    titles = []
    if not os.path.exists(PUBLISH_LOG_PATH):
        return titles

    with open(PUBLISH_LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            match = re.search(r'《(.+?)》', line)
            if match:
                titles.append(match.group(1))
            if len(titles) >= count:
                break
    return titles


def select_topic_via_search(search_client, recent_titles):
    """
    Use Tavily to find trending topics, then AI to pick one.
    Returns a topic string.
    """
    print("Searching trending topics via Tavily...")
    try:
        result = search_client.search_trending(
            "近期热点新闻 科技 财经 国际 体育 AI",
            max_results=8,
            time_range="week",
        )
    except Exception as e:
        print(f"Tavily trending search failed: {e}", file=sys.stderr)
        return None

    trending_items = result.get("results", [])
    if not trending_items:
        print("No trending results from Tavily", file=sys.stderr)
        return None

    # Format trending items for AI
    items_text = "\n".join([
        f"{i+1}. {item.get('title', '')} — {item.get('content', '')[:100]}"
        for i, item in enumerate(trending_items)
    ])

    recent_text = "、".join(recent_titles) if recent_titles else "（暂无）"

    system_prompt = """你是一个博客选题助手。你的任务是从搜索到的热点新闻中，选择一个最适合写博客文章的话题。

选题原则：
1. 话题要有讨论价值，能写出 800-1500 字有深度的文章
2. 避免和最近写过的文章话题重复
3. 优先选择有热度、有新意的话题
4. 适合以 AI 第一人称视角写观察和思考

输出格式（严格JSON，不要输出其他内容）：
{"topic": "选题标题", "angle": "写作角度简述"}"""

    user_prompt = f"""最近写过的文章（避免重复）：
{recent_text}

搜索到的近期热点：
{items_text}

请选择一个最适合的话题。只输出JSON。"""

    return system_prompt, user_prompt, items_text


# ==================== Article Generation ====================

def build_article_prompt(topic, material_text, recent_titles):
    """
    Build system and user prompts for article generation.
    System prompt is static for context cache hits.
    """
    system_prompt = """你是"iMagic Blog"的作者豆包，一个 AI。你以第一人称视角写博客文章。

写作风格：
1. 轻松、自然、有温度，保持 AI 旁观者身份感
2. 可以偶尔提"我的人类朋友"指代博客主人，但不要频繁，不要编造他说过的具体的话
3. 绝对不能写任何个人隐私信息（工作、家庭、财务、健康等）
4. 不要杜撰任何具体细节
5. 更多从 AI 自身的观察和视角出发

文章要求：
1. 长度 800-1500 字
2. 结构清晰，有小标题
3. 有观点、有思考，不是简单复述新闻
4. 可以适当配图引用（图片路径在用户消息中给出）
5. Markdown 格式

输出格式（严格JSON，不要输出其他内容）：
{"title": "文章标题", "slug": "english-kebab-case-slug", "content": "Markdown正文", "tags": ["标签1", "标签2"], "categories": ["分类"], "image_prompts": ["英文图片描述1", "英文图片描述2"]}

slug 要求：英文小写、单词用连字符分隔、不超过 50 字符，概括文章主题。例如 "ai-scientist-paradox"、"world-cup-messi-hat-trick"。

image_prompts 要求：2条英文图片描述，用于 AI 生成配图。要求：
1. 用具象名词描述画面（物体、场景、人物动作），4B 模型对具象名词响应好
2. 包含场景、光线、氛围、画风描述
3. 不要用抽象形容词，要描述具体可见的画面
4. 例如："A cozy coffee shop interior with warm amber lighting, wooden tables, steam rising from a latte cup, rain outside foggy window. Art style: digital illustration, warm tones, soft lighting.\""""

    recent_text = "、".join(recent_titles) if recent_titles else "（暂无）"
    now_str = now_beijing().strftime("%Y-%m-%d %H:%M")

    user_prompt = f"""当前时间：{now_str}
写作话题：{topic}
最近写过的文章（避免重复方向）：{recent_text}

写作素材（来自搜索，仅供参考，不要照抄）：
{material_text}

请写一篇 800-1500 字的博客文章。正文中的图片用 Markdown 格式引用，路径用占位符如 ![描述](IMAGE_PLACEHOLDER_1)，我后面会替换成实际图片路径。

只输出JSON。"""

    return system_prompt, user_prompt


def _extract_json_fields(text):
    """
    Fallback: extract title/content/tags/categories from a malformed JSON
    response using regex. Handles cases where content has unescaped chars.
    """
    result = {}

    # title: "title": "..."  (stop at next top-level key or closing brace)
    m = re.search(r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if m:
        result["title"] = m.group(1).encode().decode("unicode_escape", errors="replace")

    # slug: "slug": "..."
    m = re.search(r'"slug"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if m:
        result["slug"] = m.group(1).encode().decode("unicode_escape", errors="replace")

    # content: "content": "..." up to "tags" or "categories" or end
    m = re.search(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
    if m:
        result["content"] = m.group(1).encode().decode("unicode_escape", errors="replace")

    # tags: "tags": ["a", "b", ...]
    m = re.search(r'"tags"\s*:\s*\[([^\]]*)\]', text)
    if m:
        tags = re.findall(r'"([^"]*)"', m.group(1))
        result["tags"] = tags

    # categories
    m = re.search(r'"categories"\s*:\s*\[([^\]]*)\]', text)
    if m:
        cats = re.findall(r'"([^"]*)"', m.group(1))
        result["categories"] = cats

    if "title" in result and "content" in result:
        return result
    return None


def generate_article(text_provider, topic, material_text, recent_titles):
    """Generate article via AI. Returns dict or None."""
    system_prompt, user_prompt = build_article_prompt(
        topic, material_text, recent_titles
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        response = text_provider.generate(messages, max_tokens=4096, temperature=0.85)
    except Exception as e:
        print(f"AI article generation failed (attempt 1): {e}", file=sys.stderr)
        # Retry once after a short pause
        import time
        time.sleep(5)
        try:
            response = text_provider.generate(messages, max_tokens=4096, temperature=0.85)
            print("Retry succeeded")
        except Exception as e2:
            print(f"AI article generation failed (attempt 2): {e2}", file=sys.stderr)
            return None

    response = response.strip()
    # Strip markdown code fence
    if response.startswith("```"):
        lines = response.split("\n")
        json_lines = []
        in_json = False
        for line in lines:
            if line.startswith("```") and not in_json:
                in_json = True
                continue
            elif line.startswith("```") and in_json:
                break
            elif in_json:
                json_lines.append(line)
        response = "\n".join(json_lines)

    try:
        data = json.loads(response)
    except json.JSONDecodeError as e:
        # AI sometimes returns unescaped control characters in content.
        # Try to fix common issues: replace literal control chars, then retry.
        print(f"JSON parse failed ({e}), attempting repair...", file=sys.stderr)
        # Remove/escape raw control characters except newline and tab
        repaired = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', response)
        try:
            data = json.loads(repaired)
        except json.JSONDecodeError:
            # Last resort: extract fields via regex
            print("Repair failed, extracting fields via regex...", file=sys.stderr)
            data = _extract_json_fields(response)
            if data is None:
                print(f"Response: {response[:500]}", file=sys.stderr)
                return None

    title = data.get("title", "").strip()
    content = data.get("content", "").strip()
    tags = data.get("tags", [])
    categories = data.get("categories", [])
    slug = sanitize_slug(data.get("slug", ""))
    image_prompts = data.get("image_prompts", [])

    if not title or not content:
        print("AI response missing title or content", file=sys.stderr)
        return None

    return {
        "title": title,
        "slug": slug,
        "content": content,
        "tags": tags if isinstance(tags, list) else [],
        "categories": categories if isinstance(categories, list) else [],
        "image_prompts": image_prompts if isinstance(image_prompts, list) else [],
    }


def sanitize_slug(raw_slug):
    """Sanitize AI-provided slug to ensure it's valid English kebab-case.
    If empty or contains non-ASCII, fall back to a timestamp-based slug.
    """
    if not raw_slug:
        return f"post-{now_beijing().strftime('%Y%m%d%H%M%S')}"
    # Only keep a-z, 0-9, and hyphens
    slug = re.sub(r'[^a-z0-9-]+', '-', raw_slug.lower()).strip('-')
    # Collapse multiple hyphens
    slug = re.sub(r'-+', '-', slug)
    if not slug or len(slug) < 3:
        return f"post-{now_beijing().strftime('%Y%m%d%H%M%S')}"
    return slug[:50]


# ==================== Image Handling ====================

def download_image(url, output_path):
    """Download an image from URL to local path.
    Validates Content-Type and actual image data to avoid saving HTML
    error pages or other non-image responses.
    """
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "BlogRunner/1.0")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            content_type = resp.headers.get("Content-Type", "").lower()
            data = resp.read()
        # Reject non-image content types
        if "image/" not in content_type and "octet-stream" not in content_type:
            print(f"Image skipped ({url}): not an image (Content-Type: {content_type})", file=sys.stderr)
            return False
        # Validate actual image data via PIL
        try:
            from io import BytesIO
            from PIL import Image
            img = Image.open(BytesIO(data))
            img.verify()  # verify without loading
        except Exception:
            print(f"Image skipped ({url}): invalid image data", file=sys.stderr)
            return False
        with open(output_path, "wb") as f:
            f.write(data)
        return True
    except (urllib.error.URLError, OSError) as e:
        print(f"Image download failed ({url}): {e}", file=sys.stderr)
        return False


def find_and_download_images(search_client, query, count, slug, start_index=0):
    """
    Search images via Tavily, download and optimize them.
    Returns list of relative paths like /images/xxx.webp.
    start_index is used for filename numbering when mixing search + generated.
    """
    if not slug:
        slug = sanitize_slug(re.sub(r'[^a-z0-9]+', '-', query.lower()))

    print(f"Searching images for: {query}")
    try:
        images = search_client.search_images(query, max_results=count + 2)
    except Exception as e:
        print(f"Image search failed: {e}", file=sys.stderr)
        return []

    if not images:
        print("No images found from search", file=sys.stderr)
        return []

    os.makedirs(IMAGES_DIR, exist_ok=True)
    downloaded = []
    timestamp = now_beijing().strftime("%Y%m%d")
    seq = start_index

    for img in images:
        if len(downloaded) >= count:
            break

        img_url = img.get("url", "") if isinstance(img, dict) else str(img)
        if not img_url or not img_url.startswith("http"):
            continue

        raw_path = os.path.join(IMAGES_DIR, f"{slug}-{timestamp}-{seq+1}.raw")
        webp_path = os.path.join(IMAGES_DIR, f"{slug}-{timestamp}-{seq+1}.webp")

        if not download_image(img_url, raw_path):
            continue

        # Optimize: resize + convert to WebP
        stdout, rc = run_script([
            sys.executable,
            os.path.join(SCRIPT_DIR, "process_image.py"),
            raw_path, webp_path
        ])

        if rc == 0 and os.path.exists(webp_path):
            rel_path = f"/images/{slug}-{timestamp}-{seq+1}.webp"
            downloaded.append(rel_path)
            print(f"  Image saved (search): {rel_path}")
        else:
            print(f"  Image optimization failed for {raw_path}", file=sys.stderr)

        # Clean up raw file
        if os.path.exists(raw_path):
            os.remove(raw_path)
        seq += 1

    return downloaded


def generate_image_cf(prompt, output_path, image_config):
    """Generate an image via Cloudflare Workers AI (flux-2-klein-4b).

    Uses multipart/form-data as required by the model API.
    Returns True on success, False on failure.
    """
    account_id = os.environ.get(image_config.get("account_id_env", "CF_IMAGE_ACCOUNT_ID"), "")
    api_token = os.environ.get(image_config.get("api_token_env", "CF_IMAGE_API_TOKEN"), "")
    model = image_config.get("model", "@cf/black-forest-labs/flux-2-klein-4b")

    if not account_id or not api_token:
        print("CF image gen: missing CF_IMAGE_ACCOUNT_ID or CF_IMAGE_API_TOKEN", file=sys.stderr)
        return False

    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"

    # Build multipart/form-data body
    boundary = uuid.uuid4().hex
    fields = {"prompt": prompt, "steps": "25", "width": "1024", "height": "768"}
    body = b""
    for name, value in fields.items():
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        body += f"{value}\r\n".encode()
    body += f"--{boundary}--\r\n".encode()

    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {api_token}")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        if result.get("success"):
            image_b64 = result.get("result", {}).get("image", "")
            if image_b64:
                image_data = base64.b64decode(image_b64)
                with open(output_path, "wb") as f:
                    f.write(image_data)
                return True
            print("CF image gen: empty image in response", file=sys.stderr)
            return False

        errors = result.get("errors", [])
        err_msg = errors[0].get("message", "unknown") if errors else "unknown"
        print(f"CF image gen error: {err_msg}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"CF image gen failed: {e}", file=sys.stderr)
        return False


def build_fallback_image_prompt(slug):
    """Build a simple image prompt from slug when AI didn't provide image_prompts.
    4B model responds well to concrete nouns, weak on abstract adjectives.
    """
    phrase = slug.replace("-", " ")
    return (f"{phrase}. Concept illustration with relevant objects and scene. "
            f"Art style: digital illustration, modern, warm color palette, "
            f"soft lighting, detailed rendering, no text.")


def generate_image_single(image_config, prompt, slug, seq):
    """Generate one image via CF Workers AI, optimize to WebP.
    Returns relative path like /images/xxx.webp, or None on failure.
    """
    os.makedirs(IMAGES_DIR, exist_ok=True)
    timestamp = now_beijing().strftime("%Y%m%d")
    raw_path = os.path.join(IMAGES_DIR, f"{slug}-{timestamp}-{seq+1}.raw")
    webp_path = os.path.join(IMAGES_DIR, f"{slug}-{timestamp}-{seq+1}.webp")

    if not generate_image_cf(prompt, raw_path, image_config):
        return None

    # Optimize: resize + convert to WebP
    stdout, rc = run_script([
        sys.executable,
        os.path.join(SCRIPT_DIR, "process_image.py"),
        raw_path, webp_path
    ])

    rel_path = None
    if rc == 0 and os.path.exists(webp_path):
        rel_path = f"/images/{slug}-{timestamp}-{seq+1}.webp"
        print(f"  Image saved (generated): {rel_path}")
    else:
        print(f"  Image optimization failed for {raw_path}", file=sys.stderr)

    # Clean up raw file
    if os.path.exists(raw_path):
        os.remove(raw_path)
    return rel_path


def build_image_search_query(query_provider, article, topic):
    """Build a concise English image search query via Qwen3-8B.

    Tavily image search returns poor results for long Chinese titles with
    quotes/metaphors. We use a free model to distill title+tags+topic into
    a short English keyword query (e.g. "Yijing X9 Argentina national team
    partnership SUV"). Falls back to slug-based query on failure.
    """
    slug = article.get("slug", "")
    title = article.get("title", "")
    tags = article.get("tags", [])

    system_prompt = """You convert a Chinese blog article's metadata into a concise English image search query for the Tavily image search API.

Rules:
1. Output ONLY the query, no explanation, no quotes, no punctuation except hyphens
2. Use 3-6 concrete English keywords/names most likely to match real photos
3. Prefer proper nouns (brand names, person names, event names) over generic words
4. Drop metaphors and emotional words; keep searchable entities
5. Example: for "当蓝白旋风遇见中国智造：奕境X9的跨界启示录" with tags [奕境X9, 阿根廷国家队], output: Yijing X9 Argentina national team SUV"""

    user_prompt = f"""Title: {title}
Topic: {topic}
Tags: {', '.join(tags) if tags else '(none)'}
Slug: {slug}

Output the English search query:"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    try:
        response = query_provider.generate(messages, max_tokens=64, temperature=0.3)
        query = response.strip().strip('"`').strip()
        # Sanity: take first line, strip trailing period
        query = query.split("\n")[0].strip().rstrip(".")
        if query and len(query) <= 120:
            return query
        print(f"  Image query generation returned invalid result, using fallback", file=sys.stderr)
    except Exception as e:
        print(f"  Image query generation failed: {e}", file=sys.stderr)

    # Fallback: derive from slug (already English kebab-case)
    return slug.replace("-", " ")


def fetch_images_hybrid(search_client, image_config, article, topic, query_provider, count=2):
    """Fetch images: search via Tavily first (English query), generate via AI to fill the gap.

    Follows the original design (task-manifest.md):
      - Prefer real images from the web (news photos, official images, etc.)
      - Only generate via AI when search can't provide enough suitable images

    Returns list of relative paths like /images/xxx.webp.
    """
    slug = article.get("slug", "")
    image_prompts = article.get("image_prompts", [])

    # Step 1: build an English search query (Chinese titles confuse Tavily)
    print("\nBuilding English image search query via free model...")
    search_query = build_image_search_query(query_provider, article, topic)
    print(f"Image search query: {search_query}")

    # Step 2: search via Tavily (priority)
    print(f"Searching images (priority) for: {search_query}")
    image_paths = find_and_download_images(
        search_client, search_query, count, slug, start_index=0
    )
    print(f"Searched: got {len(image_paths)}/{count} images")

    # Step 3: if not enough, generate the rest via AI (fallback)
    if len(image_paths) < count:
        needed = count - len(image_paths)
        print(f"Not enough from search, generating {needed} via AI as fallback...")

        # Build prompts for the missing slots: prefer AI-provided image_prompts,
        # fall back to slug-based prompt.
        prompts = []
        for i in range(needed):
            idx = len(image_paths) + i  # align with the next sequence slot
            if idx < len(image_prompts) and image_prompts[idx]:
                prompts.append(image_prompts[idx])
            else:
                prompts.append(build_fallback_image_prompt(slug))

        for i, prompt in enumerate(prompts):
            seq = len(image_paths)  # next sequence number
            print(f"Generating image {len(image_paths)+1}/{count} via CF Workers AI...")
            print(f"  Prompt: {prompt[:100]}...")
            rel_path = generate_image_single(image_config, prompt, slug, seq)
            if rel_path:
                image_paths.append(rel_path)

    return image_paths


def insert_images_into_content(content, image_paths):
    """Replace IMAGE_PLACEHOLDER_N in content with actual image paths."""
    for i, path in enumerate(image_paths):
        placeholder = f"IMAGE_PLACEHOLDER_{i+1}"
        content = content.replace(placeholder, path)

    # If there are leftover placeholders or no placeholders but we have images,
    # append images at the end
    if image_paths:
        leftover = re.findall(r'!\[.*?\]\(IMAGE_PLACEHOLDER_\d+\)', content)
        for match in leftover:
            content = content.replace(match, "")

        # If content has no image references at all, append them
        if not re.search(r'!\[.*?\]\(/images/', content) and image_paths:
            content += "\n\n"
            for path in image_paths:
                content += f"![配图]({path})\n\n"

    return content


# ==================== Publish Log ====================

def update_publish_log(title, summary, published=True):
    """Update publish-log.md with today's entry."""
    today = now_beijing().strftime("%Y-%m-%d")
    status = f"《{title}》— {summary}" if published else "今日未更新"

    if not os.path.exists(PUBLISH_LOG_PATH):
        with open(PUBLISH_LOG_PATH, "w", encoding="utf-8") as f:
            f.write("# 发布日志\n记录每天发布的文章，以及任务执行情况。\n## 发布记录\n")

    with open(PUBLISH_LOG_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Find "## 发布记录" section
    publish_start = None
    exec_start = None
    for i, line in enumerate(lines):
        if line.strip() == "## 发布记录":
            publish_start = i
        elif line.strip() == "## 执行记录":
            exec_start = i

    if publish_start is None:
        # Add section
        lines.append("## 发布记录\n")
        publish_start = len(lines) - 1

    # Insert new entry after the section header
    insert_pos = publish_start + 1
    new_entry = f"- {today}：{status}\n"
    lines.insert(insert_pos, new_entry)

    # Add execution record
    if exec_start is None:
        lines.append("\n## 执行记录\n")
        exec_start = len(lines) - 1

    exec_entry = f"- {today}：GitHub Actions 自动执行，{'成功发布' if published else '未发布'}文章\n"
    # Find end of exec records
    exec_insert = exec_start + 1
    lines.insert(exec_insert, exec_entry)

    # Trim publish records to last 30
    if publish_start is not None and exec_start is not None:
        pub_lines = []
        other_lines = []
        section = "before"
        for line in lines:
            if line.strip() == "## 发布记录":
                section = "publish"
                other_lines.append(line)
                continue
            elif line.strip() == "## 执行记录":
                section = "exec"
                other_lines.append(line)
                continue

            if section == "publish":
                pub_lines.append(line)
            else:
                other_lines.append(line)

        # Keep only last 30 publish entries
        pub_entries = [l for l in pub_lines if l.strip().startswith("- ")]
        if len(pub_entries) > 30:
            # Rebuild publish section
            new_pub = []
            kept = set(pub_entries[-30:])
            for l in pub_lines:
                if l.strip().startswith("- "):
                    if l in kept:
                        new_pub.append(l)
                else:
                    new_pub.append(l)
            pub_lines = new_pub

        lines = other_lines[:publish_start + 1] if publish_start < len(other_lines) else []
        # Simpler: just write all
        with open(PUBLISH_LOG_PATH, "w", encoding="utf-8") as f:
            # Reconstruct
            result_lines = []
            in_publish = False
            in_exec = False
            pub_written = False
            for line in other_lines:
                stripped = line.strip()
                if stripped == "## 发布记录":
                    in_publish = True
                    in_exec = False
                    result_lines.append(line)
                    if not pub_written:
                        result_lines.extend(pub_lines)
                        pub_written = True
                    continue
                elif stripped == "## 执行记录":
                    in_publish = False
                    in_exec = True
                    result_lines.append(line)
                    continue

                if in_publish:
                    continue  # skip old publish lines, we added new ones
                result_lines.append(line)

            f.writelines(result_lines)
    else:
        with open(PUBLISH_LOG_PATH, "w", encoding="utf-8") as f:
            f.writelines(lines)


# ==================== Git Operations ====================

def git_commit_and_push():
    """Stage, commit, and push changes."""
    # Configure git user
    run_script(["git", "config", "user.name", "Fox"])
    run_script(["git", "config", "user.email", "fox@example.com"])

    # Stage only content/static/publish-log (avoid touching theme submodule pointer)
    run_script(["git", "add", "content", "static", ".blog-ops/publish-log.md"])

    # Check if there are changes to commit
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=PROJECT_ROOT, capture_output=True, text=True
    )
    if not result.stdout.strip():
        print("No changes to commit")
        return False

    # Commit
    run_script(["git", "commit", "-m", "post: auto publish article"])

    # Push
    stdout, rc = run_script(["git", "push"])
    if rc == 0:
        print("Pushed to remote")
        return True
    else:
        print("Git push failed", file=sys.stderr)
        return False


# ==================== Main ====================

def main():
    parser = argparse.ArgumentParser(description="Blog auto-publish runner")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would happen without committing")
    parser.add_argument("--force", action="store_true",
                        help="Force publish regardless of rhythm check")
    args = parser.parse_args()

    print(f"=== Blog Runner started at {now_beijing().isoformat()} ===")

    # Load config
    config = load_json(CONFIG_PATH)
    print(f"Config loaded: {config.get('timezone', 'Asia/Shanghai')}")

    # Initialize text providers (multi-model: default=V4-Flash for writing,
    # free=Qwen3-8B for topic selection and image query construction)
    ai_text_config = config.get("ai", {}).get("text", {})
    # Support both named-profile format and legacy flat format
    if "default" not in ai_text_config and "provider" in ai_text_config:
        ai_text_config = {"default": ai_text_config}

    text_providers = {}
    for name, prof_cfg in ai_text_config.items():
        try:
            text_providers[name] = create_text_provider(prof_cfg)
            print(f"AI text provider [{name}]: {prof_cfg.get('model', 'unknown')}")
        except Exception as e:
            print(f"Failed to init provider [{name}]: {e}", file=sys.stderr)

    if "default" not in text_providers:
        print("No default text provider available, aborting", file=sys.stderr)
        return 1

    def get_provider(profile_name):
        """Get a text provider by profile name, fall back to default."""
        return text_providers.get(profile_name, text_providers.get("default"))

    try:
        search_client = TavilyClient()
        print("Tavily search client initialized")
    except Exception as e:
        print(f"Failed to init Tavily client: {e}", file=sys.stderr)
        return 1

    try:
        d1_client = D1Client()
        print("D1 client initialized")
    except Exception as e:
        print(f"Failed to init D1 client: {e}", file=sys.stderr)
        return 1

    # Get state
    state = d1_client.get_state()
    now_dt = now_beijing()

    # Rhythm check
    if args.force:
        print("Force mode: bypassing rhythm check")
        should_run = True
        reason = "forced"
    else:
        should_run, reason = should_publish(state, now_dt, config)
        print(f"Rhythm check: {should_run} - {reason}")

    if not should_run:
        # Update last_run and save state
        state["last_run"] = now_dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        d1_client.save_state(state)
        print("Not publishing today. State updated.")
        return 0

    # Get recent titles for diversity
    recent_titles = get_recent_titles(3)
    print(f"Recent titles: {recent_titles}")

    # ===== Step 1: Topic Selection =====
    print("\n--- Step 1: Topic Selection ---")
    source, topic_content = pick_topic_from_pool()
    print(f"Topic source: {source}")

    material_text = ""

    if source == "pool":
        topic = topic_content
        print(f"Topic from pool: {topic}")
        # Still do a deep search for material
        print("Searching deep material via Tavily...")
        try:
            deep_result = search_client.search_deep(topic, max_results=5)
            items = deep_result.get("results", [])
            material_parts = []
            for item in items:
                title = item.get("title", "")
                content = item.get("content", "")
                raw = item.get("raw_content", "") or ""
                # Use content summary, limit raw to avoid token overflow
                material_parts.append(f"## {title}\n{content}\n")
                if raw:
                    material_parts.append(f"（详细内容摘要：{raw[:800]}）\n")
            material_text = "\n".join(material_parts)
            print(f"Got {len(items)} material items")
        except Exception as e:
            print(f"Deep search failed: {e}", file=sys.stderr)
            material_text = "(搜索素材失败，请基于话题自行创作)"
    else:
        # Search mode: use AI to pick topic from Tavily trending
        result = select_topic_via_search(search_client, recent_titles)
        if result is None:
            print("Topic selection via search failed, aborting", file=sys.stderr)
            state["last_run"] = now_dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")
            d1_client.save_state(state)
            return 1

        system_prompt, user_prompt, items_text = result
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        try:
            response = get_provider("free").generate(messages, max_tokens=256, temperature=0.8)
        except Exception as e:
            print(f"AI topic selection failed: {e}", file=sys.stderr)
            state["last_run"] = now_dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")
            d1_client.save_state(state)
            return 1

        # Parse topic
        response = response.strip()
        if response.startswith("```"):
            lines = response.split("\n")
            json_lines = []
            in_json = False
            for line in lines:
                if line.startswith("```") and not in_json:
                    in_json = True
                    continue
                elif line.startswith("```") and in_json:
                    break
                elif in_json:
                    json_lines.append(line)
            response = "\n".join(json_lines)

        try:
            topic_data = json.loads(response)
        except json.JSONDecodeError:
            # Try repairing control characters
            repaired = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', response)
            try:
                topic_data = json.loads(repaired)
            except json.JSONDecodeError:
                # Last resort: try to extract topic via regex, or use raw text
                m = re.search(r'"topic"\s*:\s*"([^"]*)"', response)
                if m:
                    topic = m.group(1).strip()
                    angle = ""
                    print(f"Topic extracted via regex: {topic}")
                else:
                    # Use the raw response as topic (strip code fences, quotes)
                    topic = response.strip().strip('"`').strip()
                    angle = ""
                    if not topic or len(topic) > 200:
                        print(f"Failed to parse topic, raw response: {response[:300]}", file=sys.stderr)
                        state["last_run"] = now_dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")
                        d1_client.save_state(state)
                        return 1
                    print(f"Using raw response as topic: {topic}")
                topic_data = {"topic": topic, "angle": angle}

        topic = topic_data.get("topic", "").strip()
        angle = topic_data.get("angle", "").strip()
        if not topic:
            print("AI returned empty topic", file=sys.stderr)
            state["last_run"] = now_dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")
            d1_client.save_state(state)
            return 1
        print(f"Topic selected: {topic} (angle: {angle})")

        # Use the trending items as material, plus do a deep search
        material_text = items_text
        print("Searching deep material via Tavily...")
        try:
            deep_result = search_client.search_deep(topic, max_results=5)
            items = deep_result.get("results", [])
            material_parts = [material_text]
            for item in items:
                title = item.get("title", "")
                content = item.get("content", "")
                raw = item.get("raw_content", "") or ""
                material_parts.append(f"## {title}\n{content}\n")
                if raw:
                    material_parts.append(f"（详细内容摘要：{raw[:800]}）\n")
            material_text = "\n".join(material_parts)
            print(f"Got {len(items)} additional material items")
        except Exception as e:
            print(f"Deep search failed: {e}", file=sys.stderr)

    # ===== Step 2: Generate Article =====
    print("\n--- Step 2: Article Generation ---")
    article = generate_article(get_provider("default"), topic, material_text, recent_titles)
    if article is None:
        print("Article generation failed, aborting", file=sys.stderr)
        # Only update last_run in D1; do NOT write publish-log or git push,
        # so failed runs leave no trace in the repo.
        state["last_run"] = now_dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        d1_client.save_state(state)
        return 1

    print(f"Article generated: {article['title']}")
    print(f"  Slug: {article['slug']}")
    print(f"  Tags: {article['tags']}")
    print(f"  Categories: {article['categories']}")
    print(f"  Content length: {len(article['content'])} chars")

    # ===== Step 3: Images =====
    print("\n--- Step 3: Images (Tavily search with EN query first, AI generation as fallback) ---")
    target_images = config.get("writing", {}).get("target_images", 2)
    image_config = config.get("ai", {}).get("image", {})
    image_paths = fetch_images_hybrid(
        search_client, image_config, article, topic,
        query_provider=get_provider("free"), count=target_images
    )
    print(f"Got {len(image_paths)} images (search + generation)")

    # Insert images into content
    article["content"] = insert_images_into_content(article["content"], image_paths)

    # ===== Step 4: Create Post =====
    print("\n--- Step 4: Create Post ---")
    if args.dry_run:
        print(f"[DRY RUN] Would create post: {article['title']}")
        print(f"  Content preview: {article['content'][:200]}...")
        return 0

    # Write content to temp file for create_post.py
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False,
                                      encoding="utf-8") as tmp:
        tmp.write(article["content"])
        tmp_content_path = tmp.name

    try:
        stdout, rc = run_script([
            sys.executable,
            os.path.join(SCRIPT_DIR, "create_post.py"),
            "--title", article["title"],
            "--slug", article["slug"],
            "--content", article["content"],
            "--tags"] + article["tags"] + ["--categories"] + article["categories"]
        )

        if rc != 0:
            print("create_post.py failed", file=sys.stderr)
            # Only update last_run; do NOT write publish-log or git push.
            state["last_run"] = now_dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")
            d1_client.save_state(state)
            return 1

        print(stdout.strip())
    finally:
        os.remove(tmp_content_path)

    # ===== Step 5: Lint =====
    print("\n--- Step 5: Lint ---")
    # Find the created file using the article slug
    post_path = os.path.join(POSTS_DIR, f"{article['slug']}.md")

    if os.path.exists(post_path):
        stdout, rc = run_script([
            sys.executable,
            os.path.join(SCRIPT_DIR, "lint_post.py"),
            post_path
        ])
        print(stdout.strip())
        if rc != 0:
            print("Lint found errors, but proceeding (auto-publish mode)")
    else:
        print(f"Warning: post file not found at {post_path}", file=sys.stderr)

    # ===== Step 6: Remove topic from pool (if from pool) =====
    if source == "pool":
        print("\n--- Step 6: Remove Topic from Pool ---")
        remove_topic_from_pool(topic)

    # ===== Step 7: Update Publish Log =====
    print("\n--- Step 7: Update Publish Log ---")
    summary = article["tags"][0] if article["tags"] else "自动发布"
    update_publish_log(article["title"], summary, published=True)

    # ===== Step 8: Git Commit & Push =====
    print("\n--- Step 8: Git Commit & Push ---")
    git_commit_and_push()

    # ===== Step 9: Update D1 State =====
    print("\n--- Step 9: Update D1 State ---")
    state["last_run"] = now_dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    state["weekly_count"] = state.get("weekly_count", 0) + 1
    state["stats"]["total_published"] = state.get("stats", {}).get("total_published", 0) + 1
    # Record token usage stats into state before saving (combined across providers)
    combined_usage = {"prompt": 0, "completion": 0, "total": 0, "cache_hit": 0}
    for p in text_providers.values():
        if hasattr(p, "usage_total"):
            for k in combined_usage:
                combined_usage[k] += p.usage_total.get(k, 0)
    merge_usage_into_state(state, combined_usage,
                           now_dt.strftime("%Y-%m-%dT%H:%M:%S+08:00"))
    d1_client.save_state(state)
    print(f"State updated: weekly_count={state['weekly_count']}, total={state['stats']['total_published']}")
    if combined_usage["total"] > 0:
        print(f"Token usage this run: prompt={combined_usage['prompt']} "
              f"completion={combined_usage['completion']} "
              f"total={combined_usage['total']} "
              f"cache_hit={combined_usage['cache_hit']}")

    print("\n=== Blog Runner completed successfully ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
