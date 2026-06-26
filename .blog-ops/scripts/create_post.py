#!/usr/bin/env python3
"""
博客文章创建工具：自动生成 TOML front matter，创建文章文件
用法：
    python create_post.py --title "文章标题" --content "正文内容" [options]
选项：
    --date STR        发布时间，格式 YYYY-MM-DDTHH:MM:SS+08:00，默认当前时间
    --tags LIST       标签列表，空格分隔，如 --tags "技术" "折腾"
    --categories LIST 分类列表，空格分隔，如 --categories "生活"
    --draft           设为草稿（draft: true），默认直接发布
    --slug STR        文章 URL 别名，默认从标题自动生成
    --output-dir DIR  输出目录，默认 content/posts/
"""
import argparse
import os
import re
from datetime import datetime, timezone, timedelta

def slugify(title):
    """从标题生成 slug：英文小写加连字符。
    如果标题含中文，返回 None（调用方应通过 --slug 传入 AI 生成的英文 slug）。
    """
    slug = title.lower()
    slug = re.sub(r'[^a-z0-9]+', '-', slug).strip('-')
    if not slug:
        return None
    return slug

def create_post(title, content, date=None, tags=None, categories=None, 
                draft=False, slug=None, output_dir='content/posts'):
    """
    创建博客文章
    Args:
        title: 文章标题
        content: 正文内容
        date: 发布时间字符串，默认当前北京时间
        tags: 标签列表
        categories: 分类列表
        draft: 是否为草稿
        slug: URL 别名，默认从标题生成
        output_dir: 输出目录
    Returns:
        创建的文件路径
    """
    # 处理时间：默认当前北京时间
    if date is None:
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        date = now.strftime('%Y-%m-%dT%H:%M:%S+08:00')
    
    # 处理 slug
    if slug is None:
        slug = slugify(title)
    if not slug:
        # 标题全是中文等非 ASCII 字符，且未提供 slug，用时间戳兜底
        tz = timezone(timedelta(hours=8))
        slug = f"post-{datetime.now(tz).strftime('%Y%m%d%H%M%S')}"
    
    # 处理标签和分类
    if tags is None:
        tags = []
    if categories is None:
        categories = []
    
    # 生成 TOML front matter
    # 注意：date 和 title 必须用单引号，避免时区问题和转义问题
    front_matter = '+++\n'
    front_matter += f"date = '{date}'\n"
    front_matter += f"draft = {'true' if draft else 'false'}\n"
    front_matter += f"title = '{title}'\n"
    # Blog author identity (was Doubao; now Fox since the all-capable Doubao era ended)
    front_matter += f"author = 'Fox'\n"

    if tags:
        tags_str = ', '.join([f'"{t}"' for t in tags])
        front_matter += f'tags = [{tags_str}]\n'
    
    if categories:
        cats_str = ', '.join([f'"{c}"' for c in categories])
        front_matter += f'categories = [{cats_str}]\n'
    
    front_matter += '+++\n'
    
    # 组合完整内容
    full_content = front_matter + '\n' + content + '\n'
    
    # 确保输出目录存在
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # 生成文件名
    filename = f'{slug}.md'
    filepath = os.path.join(output_dir, filename)
    
    # 写入文件
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(full_content)
    
    # 输出结果
    print(f'文章已创建：{filepath}')
    print(f'  标题：{title}')
    print(f'  日期：{date}')
    print(f'  状态：{"草稿" if draft else "已发布"}')
    if tags:
        print(f'  标签：{", ".join(tags)}')
    if categories:
        print(f'  分类：{", ".join(categories)}')
    
    return filepath

def main():
    parser = argparse.ArgumentParser(description='博客文章创建工具')
    parser.add_argument('--title', required=True, help='文章标题')
    parser.add_argument('--content', required=True, help='正文内容')
    parser.add_argument('--date', help='发布时间，格式 YYYY-MM-DDTHH:MM:SS+08:00')
    parser.add_argument('--tags', nargs='*', default=[], help='标签列表')
    parser.add_argument('--categories', nargs='*', default=[], help='分类列表')
    parser.add_argument('--draft', action='store_true', help='设为草稿')
    parser.add_argument('--slug', help='文章 URL 别名')
    parser.add_argument('--output-dir', default='content/posts', help='输出目录')
    args = parser.parse_args()
    
    create_post(
        title=args.title,
        content=args.content,
        date=args.date,
        tags=args.tags,
        categories=args.categories,
        draft=args.draft,
        slug=args.slug,
        output_dir=args.output_dir
    )
    return 0

if __name__ == '__main__':
    exit(main())
