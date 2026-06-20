#!/usr/bin/env python3
"""
Blog 文章检查工具
自动化检查文章的常见问题，减少踩坑
"""

import argparse
import os
import re
import sys
from datetime import datetime


def check_front_matter(content):
    """检查 front matter 格式"""
    issues = []
    
    # 检查是否有 front matter
    if not content.startswith('+++'):
        issues.append('❌ 没有找到 TOML front matter（应该以 +++ 开头）')
        return issues
    
    # 提取 front matter
    match = re.match(r'^\+\+\+\n(.*?)\n\+\+\+', content, re.DOTALL)
    if not match:
        issues.append('❌ front matter 格式不正确，没有找到结束的 +++')
        return issues
    
    fm_content = match.group(1)
    
    # 检查 date 字段
    date_match = re.search(r"date\s*=\s*'([^']+)'", fm_content)
    if not date_match:
        # 检查是不是用了双引号或者没加引号
        date_match_bad = re.search(r'date\s*=\s*', fm_content)
        if date_match_bad:
            issues.append('❌ date 字段没有用单引号包裹！这会导致时区解析错误，文章可能不显示')
        else:
            issues.append('❌ 没有找到 date 字段')
    else:
        date_str = date_match.group(1)
        # 检查日期格式是否合理
        try:
            # 尝试解析 ISO 格式
            if '+' in date_str or '-' in date_str[10:]:
                # 有时区信息
                datetime.fromisoformat(date_str)
            else:
                # 没有时区信息
                issues.append('⚠️  date 没有时区信息，建议加上 +08:00')
        except ValueError:
            issues.append(f'❌ date 格式无法解析：{date_str}')
    
    # 检查 title 字段
    title_match = re.search(r"title\s*=\s*'([^']*)'", fm_content)
    if not title_match:
        # 检查是不是用了双引号
        title_match_bad = re.search(r'title\s*=\s*"', fm_content)
        if title_match_bad:
            issues.append('⚠️  title 用了双引号，如果标题里包含特殊字符可能会有问题，建议用单引号')
        else:
            issues.append('⚠️  没有找到 title 字段')
    
    # 检查 draft 字段
    draft_match = re.search(r'draft\s*=\s*(true|false)', fm_content)
    if not draft_match:
        issues.append('⚠️  没有找到 draft 字段')
    
    return issues


def check_future_date(content):
    """检查日期是否是未来时间"""
    issues = []
    
    date_match = re.search(r"date\s*=\s*'([^']+)'", content)
    if date_match:
        date_str = date_match.group(1)
        try:
            # 尝试解析
            if '+' in date_str:
                date_obj = datetime.fromisoformat(date_str)
            else:
                date_obj = datetime.fromisoformat(date_str + '+08:00')
            
            now = datetime.now(date_obj.tzinfo) if date_obj.tzinfo else datetime.now()
            
            if date_obj > now:
                issues.append(f'❌ 文章日期是未来时间：{date_str}，Hugo 不会发布这篇文章')
        except ValueError:
            pass  # 格式问题已经在前面检查过了
    
    return issues


def check_external_images(content):
    """检查是否引用了外部图片链接"""
    issues = []
    
    # 匹配 Markdown 图片语法：![alt](url)
    img_pattern = r'!\[.*?\]\((.*?)\)'
    matches = re.findall(img_pattern, content)
    
    external_imgs = []
    for url in matches:
        if url.startswith('http://') or url.startswith('https://'):
            external_imgs.append(url)
    
    if external_imgs:
        issues.append(f'❌ 发现 {len(external_imgs)} 张外部图片链接，必须下载到本地：')
        for url in external_imgs:
            issues.append(f'   - {url}')
    
    return issues


def check_image_files(content, content_dir):
    """检查引用的本地图片文件是否存在"""
    issues = []
    
    img_pattern = r'!\[.*?\]\((.*?)\)'
    matches = re.findall(img_pattern, content)
    
    local_imgs = [url for url in matches if not url.startswith('http')]
    
    for img_path in local_imgs:
        # 处理相对路径
        if img_path.startswith('/'):
            # 绝对路径（相对于 static 目录）
            full_path = os.path.join(content_dir, 'static', img_path.lstrip('/'))
        else:
            # 相对路径（相对于文章文件）
            full_path = os.path.join(content_dir, img_path)
        
        if not os.path.exists(full_path):
            issues.append(f'❌ 图片文件不存在：{img_path}')
        else:
            # 检查文件大小
            file_size = os.path.getsize(full_path)
            if file_size > 2 * 1024 * 1024:  # 大于 2MB
                issues.append(f'⚠️  图片文件较大：{img_path} ({file_size/1024/1024:.1f} MB)，建议优化')
    
    return issues


def check_post(filepath, content_dir=None):
    """检查单篇文章"""
    issues = []
    
    # 读取文件
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        return [f'❌ 无法读取文件：{e}']
    
    # 如果没有指定 content_dir，用项目根目录（假设文章在 content/posts/ 下）
    if not content_dir:
        # 往上找两级：content/posts/article.md -> content/posts -> content -> 根目录
        content_dir = os.path.dirname(os.path.dirname(os.path.dirname(filepath)))
    
    # 各项检查
    issues.extend(check_front_matter(content))
    issues.extend(check_future_date(content))
    issues.extend(check_external_images(content))
    issues.extend(check_image_files(content, content_dir))
    
    return issues


def main():
    parser = argparse.ArgumentParser(description='检查博客文章格式')
    parser.add_argument('files', nargs='*', help='要检查的文章文件路径')
    parser.add_argument('--all', action='store_true', help='检查所有文章')
    parser.add_argument('--content-dir', default=None, help='项目根目录（用于查找图片文件）')
    
    args = parser.parse_args()
    
    files_to_check = []
    
    if args.all:
        # 检查 content/posts/ 目录下所有文章
        posts_dir = os.path.join(args.content_dir or '.', 'content', 'posts')
        if os.path.exists(posts_dir):
            for filename in os.listdir(posts_dir):
                if filename.endswith('.md'):
                    files_to_check.append(os.path.join(posts_dir, filename))
        else:
            print(f'❌ 找不到文章目录：{posts_dir}')
            sys.exit(1)
    else:
        files_to_check = args.files
    
    if not files_to_check:
        print('请指定要检查的文件，或使用 --all 检查所有文章')
        sys.exit(1)
    
    # 统计
    total_issues = 0
    total_files = len(files_to_check)
    files_with_issues = 0
    
    for filepath in files_to_check:
        issues = check_post(filepath, args.content_dir)
        
        if issues:
            files_with_issues += 1
            total_issues += len(issues)
            print(f'\n📄 {os.path.basename(filepath)}')
            for issue in issues:
                print(f'  {issue}')
    
    # 总结
    print(f'\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
    print(f'检查完成：{total_files} 篇文章')
    if total_issues == 0:
        print(f'✅ 全部通过，没有发现问题')
    else:
        print(f'⚠️  发现 {total_issues} 个问题，涉及 {files_with_issues} 篇文章')
        sys.exit(1)


if __name__ == '__main__':
    main()
