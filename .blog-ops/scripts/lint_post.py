#!/usr/bin/env python3
"""
博客文章格式检查工具：自动检查 front matter 格式、图片引用、时间等
用法：
    python lint_post.py <文章路径> [选项]
选项：
    --all        检查 content/posts/ 下所有文章
    --fix        自动修复能修复的问题（如 date 引号）
"""
import argparse
import os
import re
import sys
from datetime import datetime, timezone, timedelta

def parse_front_matter(content):
    """解析 TOML front matter，返回字典和错误列表"""
    errors = []
    warnings = []
    front_matter = {}
    
    # 检查是否有 +++ 包裹
    if not content.startswith('+++'):
        errors.append('front matter 格式错误：没有以 +++ 开头')
        return front_matter, errors, warnings
    
    # 提取 front matter 内容
    end_pos = content.find('+++', 3)
    if end_pos == -1:
        errors.append('front matter 格式错误：没有找到结束的 +++')
        return front_matter, errors, warnings
    
    fm_content = content[3:end_pos].strip()
    
    # 逐行解析
    for line in fm_content.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        
        # 简单解析 key = value 格式
        match = re.match(r'^(\w+)\s*=\s*(.+)$', line)
        if match:
            key = match.group(1)
            value = match.group(2).strip()
            front_matter[key] = value
        else:
            warnings.append(f'无法解析的行：{line}')
    
    return front_matter, errors, warnings

def check_date(date_str):
    """检查 date 字段"""
    errors = []
    warnings = []
    
    # 检查是否用单引号包裹
    if not (date_str.startswith("'") and date_str.endswith("'")):
        errors.append(f'date 字段没有用单引号包裹：{date_str}')
        # 尝试提取内容
        date_str = date_str.strip("'\"")
    else:
        date_str = date_str.strip("'")
    
    # 检查格式
    try:
        # 尝试解析带时区的格式
        dt = datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%S+08:00')
        dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
    except ValueError:
        try:
            dt = datetime.fromisoformat(date_str)
        except ValueError:
            errors.append(f'date 格式无法解析：{date_str}')
            return errors, warnings, None
    
    # 检查是否是未来时间
    now = datetime.now(timezone(timedelta(hours=8)))
    if dt > now:
        errors.append(f'date 是未来时间：{date_str}（当前时间：{now.strftime("%Y-%m-%dT%H:%M:%S+08:00")}）')
    
    return errors, warnings, dt

def check_title(title_str):
    """检查 title 字段"""
    errors = []
    warnings = []
    
    # 检查是否用引号包裹
    if not (title_str.startswith("'") and title_str.endswith("'")):
        warnings.append(f'title 建议用单引号包裹：{title_str}')
    
    return errors, warnings

def check_images(content, article_path):
    """检查图片引用"""
    errors = []
    warnings = []
    
    # 查找所有图片引用：![alt](url)
    img_pattern = r'!\[.*?\]\((.*?)\)'
    images = re.findall(img_pattern, content)
    
    if not images:
        warnings.append('文章没有配图（建议每篇文章配 2-3 张图）')
        return errors, warnings
    
    article_dir = os.path.dirname(article_path)
    static_dir = os.path.join(os.path.dirname(os.path.dirname(article_dir)), 'static')
    
    for img_url in images:
        # 检查是否是外链
        if img_url.startswith('http://') or img_url.startswith('https://'):
            errors.append(f'发现外部图片链接：{img_url}（必须下载到本地）')
            continue
        
        # 检查本地图片是否存在
        if img_url.startswith('/'):
            # 绝对路径，相对于 static 目录
            img_path = os.path.join(static_dir, img_url.lstrip('/'))
        else:
            # 相对路径
            img_path = os.path.join(article_dir, img_url)
        
        if not os.path.exists(img_path):
            errors.append(f'图片文件不存在：{img_url}（查找路径：{img_path}）')
        else:
            # 检查是否是 WebP 格式
            if not img_url.lower().endswith('.webp'):
                warnings.append(f'图片不是 WebP 格式：{img_url}（建议转成 WebP）')
            
            # 检查文件大小
            file_size = os.path.getsize(img_path) / 1024
            if file_size > 500:
                warnings.append(f'图片文件较大：{img_url}（{file_size:.1f} KB，建议控制在 500KB 以内）')
    
    return errors, warnings

def lint_post(filepath):
    """检查单篇文章"""
    errors = []
    warnings = []
    
    # 读取文件
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        errors.append(f'无法读取文件：{e}')
        return errors, warnings
    
    # 解析 front matter
    fm, fm_errors, fm_warnings = parse_front_matter(content)
    errors.extend(fm_errors)
    warnings.extend(fm_warnings)
    
    if fm_errors:
        return errors, warnings
    
    # 检查 date
    if 'date' in fm:
        date_errors, date_warnings, _ = check_date(fm['date'])
        errors.extend(date_errors)
        warnings.extend(date_warnings)
    else:
        errors.append('缺少 date 字段')
    
    # 检查 title
    if 'title' in fm:
        title_errors, title_warnings = check_title(fm['title'])
        errors.extend(title_errors)
        warnings.extend(title_warnings)
    else:
        errors.append('缺少 title 字段')
    
    # 检查 draft
    if 'draft' not in fm:
        warnings.append('缺少 draft 字段（默认 false）')
    
    # 检查图片
    img_errors, img_warnings = check_images(content, filepath)
    errors.extend(img_errors)
    warnings.extend(img_warnings)
    
    return errors, warnings

def main():
    parser = argparse.ArgumentParser(description='博客文章格式检查工具')
    parser.add_argument('path', nargs='?', help='文章文件路径')
    parser.add_argument('--all', action='store_true', help='检查所有文章')
    parser.add_argument('--fix', action='store_true', help='自动修复能修复的问题')
    args = parser.parse_args()
    
    # 确定要检查的文件列表
    files_to_check = []
    
    if args.all:
        posts_dir = 'content/posts'
        if os.path.exists(posts_dir):
            for filename in os.listdir(posts_dir):
                if filename.endswith('.md'):
                    files_to_check.append(os.path.join(posts_dir, filename))
    elif args.path:
        if os.path.isdir(args.path):
            for filename in os.listdir(args.path):
                if filename.endswith('.md'):
                    files_to_check.append(os.path.join(args.path, filename))
        else:
            files_to_check.append(args.path)
    else:
        print('错误：请指定文章路径或使用 --all 参数')
        print('用法：python lint_post.py <文章路径>')
        print('      python lint_post.py --all')
        return 1
    
    if not files_to_check:
        print('没有找到要检查的文章')
        return 1
    
    # 检查所有文件
    total_errors = 0
    total_warnings = 0
    
    for filepath in files_to_check:
        errors, warnings = lint_post(filepath)
        
        if errors or warnings:
            print(f'\n📄 {filepath}')
            
            if errors:
                print(f'  ❌ 错误 ({len(errors)} 个)：')
                for e in errors:
                    print(f'     - {e}')
                total_errors += len(errors)
            
            if warnings:
                print(f'  ⚠️  警告 ({len(warnings)} 个)：')
                for w in warnings:
                    print(f'     - {w}')
                total_warnings += len(warnings)
        else:
            print(f'✅ {filepath} - 通过检查')
    
    # 总结
    print(f'\n--- 检查完成 ---')
    print(f'检查了 {len(files_to_check)} 篇文章')
    print(f'错误：{total_errors} 个')
    print(f'警告：{total_warnings} 个')
    
    if total_errors > 0:
        return 1
    return 0

if __name__ == '__main__':
    exit(main())
