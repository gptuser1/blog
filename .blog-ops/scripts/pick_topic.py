#!/usr/bin/env python3
"""
选题工具：从选题池或实时搜索中选择写作话题
用法：
    python pick_topic.py [选项]
选项：
    --pool-weight FLOAT    选题池权重，默认 0.7（70% 概率从选题池选）
    --diversity-count INT  考虑最近几篇的话题多样性，默认 3
    --topics-path PATH     选题池文件路径，默认 .blog-ops/topics.md
    --log-path PATH        发布日志路径，默认 .blog-ops/publish-log.md
    --seed INT             随机种子（用于测试）
    --dry-run              只输出结果，不修改选题池（用于测试）
输出：
    情况 A（选题池选中）：
        RESULT: pool
        TOPIC: 选题标题
        REMOVED: true/false
    情况 B（需要搜索）：
        RESULT: search
        INSTRUCTION: 搜索指令文本

注意：从选题池选中的话题会自动从选题池中删除，避免重复选中。
"""
import argparse
import os
import re
import random
import sys


def parse_topics(topics_path):
    """
    解析选题池文件，返回待写主题列表
    """
    topics = []
    
    if not os.path.exists(topics_path):
        return topics
    
    with open(topics_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    in_pending = False
    for line in lines:
        line_stripped = line.strip()
        
        # 找到"待写主题"章节
        if line_stripped.startswith('## 待写主题'):
            in_pending = True
            continue
        
        if in_pending and line_stripped.startswith('## '):
            # 遇到下一个章节，结束
            break
        
        if in_pending and line_stripped.startswith('- '):
            topic = line_stripped[2:].strip()
            if topic:
                topics.append(topic)
    
    return topics


def remove_topic_from_pool(topic, topics_path):
    """
    从选题池中删除指定的话题
    Returns:
        bool: 是否成功删除
    """
    if not os.path.exists(topics_path):
        return False
    
    with open(topics_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    in_pending = False
    new_lines = []
    removed = False
    
    for line in lines:
        line_stripped = line.strip()
        
        # 找到"待写主题"章节
        if line_stripped.startswith('## 待写主题'):
            in_pending = True
            new_lines.append(line)
            continue
        
        if in_pending and line_stripped.startswith('## '):
            # 遇到下一个章节，结束
            in_pending = False
            new_lines.append(line)
            continue
        
        if in_pending and line_stripped.startswith('- '):
            topic_text = line_stripped[2:].strip()
            if topic_text == topic and not removed:
                # 跳过这一行，即删除
                removed = True
                continue
        
        new_lines.append(line)
    
    if removed:
        with open(topics_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
    
    return removed


def parse_publish_log(log_path, count=3):
    """
    解析发布日志，返回最近 N 篇的主题摘要列表
    """
    recent_topics = []
    
    if not os.path.exists(log_path):
        return recent_topics
    
    with open(log_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    in_publish = False
    for line in lines:
        line = line.strip()
        
        # 找到"发布记录"章节
        if line.startswith('## 发布记录'):
            in_publish = True
            continue
        
        if in_publish and line.startswith('## '):
            # 遇到下一个章节，结束
            break
        
        if in_publish and line.startswith('- '):
            # 解析格式：- 2026-06-21：《标题》— 简要说明
            # 提取标题和简要说明
            match = re.search(r'《(.+?)》', line)
            if match:
                title = match.group(1)
                recent_topics.append(title)
            
            # 如果提取不到标题，用整行
            if not match:
                recent_topics.append(line)
            
            if len(recent_topics) >= count:
                break
    
    return recent_topics


def is_topic_repeated(topic, recent_topics):
    """
    简单判断选题是否和最近文章重复
    基于关键词重叠的简单判断
    """
    # 提取选题的关键词（简单分词：按标点和空格拆分）
    topic_keywords = set(re.findall(r'[\w\u4e00-\u9fff]+', topic.lower()))

    for recent in recent_topics:
        recent_keywords = set(re.findall(r'[\w\u4e00-\u9fff]+', recent.lower()))

        # 计算关键词重叠率
        if not topic_keywords or not recent_keywords:
            continue

        overlap = topic_keywords & recent_keywords
        overlap_ratio = len(overlap) / min(len(topic_keywords), len(recent_keywords))

        # 如果重叠率超过 50%，认为是重复话题
        if overlap_ratio > 0.5:
            return True

    return False


# Broad topic categories for diversity control (mirrors blog_runner.py).
# Used to detect thematic fatigue beyond mere keyword overlap, e.g. several
# AI/tech articles in a row even though their titles share few keywords.
def categorize_topic(topic):
    """Map a topic/title to a broad category for diversity control."""
    t = topic.lower()
    if any(k in t for k in ["足球", "梅西", "世界杯", "fifa", "巴萨", "阿根廷",
                            "球员", "联赛", "nba", "奥运", "体育", "补水", "国家队"]):
        return "体育"
    if any(k in t for k in ["电影", "音乐", "游戏", "asmr", "经典", "导演",
                            "演员", "b站", "纪录片", "娱乐", "文化"]):
        return "文化娱乐"
    if any(k in t for k in ["armbian", "linux", "盒子", "服务器", "部署", "教程",
                            "折腾", "emmc", "s905", "命令", "脚本", "启动"]):
        return "技术折腾"
    if any(k in t for k in ["海峡", "伊朗", "俄罗斯", "乌克兰", "地缘", "外交",
                            "制裁", "战争", "国际", "特朗普"]):
        return "国际"
    if any(k in t for k in ["股价", "股市", "上市", "ipo", "财报", "金融",
                            "市值", "投资", "财经", "经济", "消费"]):
        return "财经"
    if any(k in t for k in ["ai", "人工智能", "大模型", "智能体", "算法", "科学家",
                            "deepmind", "openai", "anthropic", "alphabet", "google",
                            "芯片", "算力", "超算", "量子", "科技", "智造",
                            "人才战争", "伦理", "治理"]):
        return "AI科技"
    if any(k in t for k in ["生活", "随笔", "咖啡", "周末", "心情", "感悟", "日常"]):
        return "生活随笔"
    return "其他"


def over_represented_category(recent_topics, threshold=2):
    """Return a category that appears >= threshold times in recent topics, else None."""
    counts = {}
    for t in recent_topics:
        cat = categorize_topic(t)
        if cat == "其他":
            continue
        counts[cat] = counts.get(cat, 0) + 1
    for cat, n in counts.items():
        if n >= threshold:
            return cat
    return None


def filter_topics(topics, recent_topics):
    """
    过滤掉和最近文章重复的选题，并执行大类多样性约束：
    若最近文章中某个大类已偏多（>=2 篇），则过滤掉属于该大类的选题，
    避免连续写同一领域的文章。
    """
    blocked_cat = over_represented_category(recent_topics, threshold=2)
    if blocked_cat:
        print(f"[diversity] blocking over-represented category: {blocked_cat}",
              file=sys.stderr)

    filtered = []
    for topic in topics:
        if is_topic_repeated(topic, recent_topics):
            continue
        if blocked_cat and categorize_topic(topic) == blocked_cat:
            print(f"[diversity] dropping pool topic in blocked category "
                  f"'{blocked_cat}': {topic}", file=sys.stderr)
            continue
        filtered.append(topic)
    return filtered


def pick_topic(pool_weight=0.7, diversity_count=3, topics_path='.blog-ops/topics.md', 
               log_path='.blog-ops/publish-log.md', seed=None):
    """
    主逻辑：选择选题
    Returns:
        (result_type, content)
        result_type: 'pool' or 'search'
        content: topic string (pool) or instruction string (search)
    """
    # 设置随机种子
    if seed is not None:
        random.seed(seed)
    
    # 解析选题池
    topics = parse_topics(topics_path)
    
    # 解析最近发布记录
    recent_topics = parse_publish_log(log_path, diversity_count)
    
    # 过滤重复选题
    filtered_topics = filter_topics(topics, recent_topics)
    
    # 搜索指令
    search_instruction = (
        "请搜索近期实时热点和新闻，选择一个值得写的话题进行创作。"
        "可以参考方向：科技前沿、科学发现、足球赛事/行业、财经大事件、国际新闻、"
        "社会观察、电影/游戏/音乐等文化娱乐、技术折腾、生活随笔、人生阶段节点、"
        "AI热点等，但不局限于这些方向，天下大事都可以写。"
        "优先选择有热度、有讨论价值的实时话题，注意避开最近3篇写过的重复方向。"
    )
    
    # 如果选题池为空，直接返回搜索
    if not filtered_topics:
        return 'search', search_instruction
    
    # 加权随机决策
    if random.random() < pool_weight:
        # 从选题池随机选一个
        selected = random.choice(filtered_topics)
        return 'pool', selected
    else:
        # 返回搜索指令
        return 'search', search_instruction


def main():
    parser = argparse.ArgumentParser(description='选题工具：从选题池或实时搜索中选择写作话题')
    parser.add_argument('--pool-weight', type=float, default=0.7, 
                        help='选题池权重，默认 0.7（70%% 概率从选题池选）')
    parser.add_argument('--diversity-count', type=int, default=3,
                        help='考虑最近几篇的话题多样性，默认 3')
    parser.add_argument('--topics-path', default='.blog-ops/topics.md',
                        help='选题池文件路径')
    parser.add_argument('--log-path', default='.blog-ops/publish-log.md',
                        help='发布日志路径')
    parser.add_argument('--seed', type=int, default=None,
                        help='随机种子（用于测试）')
    parser.add_argument('--dry-run', action='store_true',
                        help='只输出结果，不修改选题池（用于测试）')
    parser.add_argument('--no-remove', action='store_true',
                        help='选中选题但不从选题池删除（删除由调用方在发布成功后执行）')
    args = parser.parse_args()

    # 执行选题
    result_type, content = pick_topic(
        pool_weight=args.pool_weight,
        diversity_count=args.diversity_count,
        topics_path=args.topics_path,
        log_path=args.log_path,
        seed=args.seed
    )

    # 输出结果
    if result_type == 'pool':
        print(f'RESULT: pool')
        print(f'TOPIC: {content}')

        # 如果不是 dry-run 且不是 no-remove，从选题池中删除
        if not args.dry_run and not args.no_remove:
            removed = remove_topic_from_pool(content, args.topics_path)
            print(f'REMOVED: {"true" if removed else "false"}')
        else:
            print(f'REMOVED: false ({'dry-run' if args.dry_run else 'no-remove'})')

        return 0
    else:
        print(f'RESULT: search')
        print(f'INSTRUCTION: {content}')
        return 0


if __name__ == '__main__':
    exit(main())
