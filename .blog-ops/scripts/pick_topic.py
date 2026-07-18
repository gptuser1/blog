#!/usr/bin/env python3
"""
选题工具：从选题池（JSON）或实时搜索中选择写作话题
用法：
    python pick_topic.py [选项]
选项：
    --pool-weight FLOAT    选题池权重，默认 0.7（70% 概率从选题池选）
    --diversity-count INT  考虑最近几篇的话题多样性，默认 3
    --topics-path PATH     选题池文件路径，默认 .blog-ops/topics.json
    --log-path PATH        发布日志路径，默认 .blog-ops/publish-log.json
    --seed INT             随机种子（用于测试）
    --dry-run              只输出结果，不修改选题池（用于测试）
输出：
    情况 A（选题池选中）：
        RESULT: pool
        POOL_TYPE: queue | non_queue
        TOPIC: 选题标题
        REMOVED: true/false
    情况 B（需要搜索）：
        RESULT: search
        INSTRUCTION: 搜索指令文本

选题池规则：
    - queue（队列）：FIFO 顺序，优先消费，不参与多样性过滤
    - non_queue（非队列）：随机选，参与多样性过滤
    - 选题池整体占 pool_weight 概率（含 queue 和 non_queue）
"""
import argparse
import json
import os
import re
import random
import sys


def read_topics(topics_path):
    """
    读取 JSON 选题池，返回 (queue, non_queue) 列表
    """
    queue = []
    non_queue = []

    if not os.path.exists(topics_path):
        return queue, non_queue

    try:
        with open(topics_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        queue = data.get("queue", [])
        non_queue = data.get("non_queue", [])
    except (json.JSONDecodeError, IOError):
        pass

    return queue, non_queue


def write_topics(topics_path, queue, non_queue):
    """写入 JSON 选题池"""
    data = {"queue": queue, "non_queue": non_queue}
    with open(topics_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def remove_queue_first(topics_path):
    """
    从队列中移除第一条（FIFO pop）
    Returns:
        (topic, bool): (被移除的选题, 是否成功)
    """
    queue, non_queue = read_topics(topics_path)
    if not queue:
        return None, False
    topic = queue.pop(0)
    write_topics(topics_path, queue, non_queue)
    return topic, True


def remove_topic_from_pool(topic, topics_path):
    """
    从选题池中删除指定话题（内容匹配，queue 和 non_queue 都查）
    Returns:
        bool: 是否成功删除
    """
    queue, non_queue = read_topics(topics_path)
    removed = False

    if topic in queue:
        queue.remove(topic)
        removed = True
    elif topic in non_queue:
        non_queue.remove(topic)
        removed = True

    if removed:
        write_topics(topics_path, queue, non_queue)

    return removed


def parse_publish_log(log_path, count=3):
    """解析发布日志（JSON），返回最近 N 篇有标题的文章标题列表"""
    recent_topics = []

    if not os.path.exists(log_path):
        return recent_topics

    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        records = data.get("publish_records", [])
        for record in records:
            title = record.get("title", "")
            if title:  # 只取有标题的记录（跳过自动执行占位行）
                recent_topics.append(title)
            if len(recent_topics) >= count:
                break
    except (json.JSONDecodeError, IOError):
        pass

    return recent_topics


def is_topic_repeated(topic, recent_topics):
    """判断选题是否和最近文章重复（基于关键词重叠）"""
    topic_keywords = set(re.findall(r'[\w\u4e00-\u9fff]+', topic.lower()))

    for recent in recent_topics:
        recent_keywords = set(re.findall(r'[\w\u4e00-\u9fff]+', recent.lower()))
        if not topic_keywords or not recent_keywords:
            continue
        overlap = topic_keywords & recent_keywords
        overlap_ratio = len(overlap) / min(len(topic_keywords), len(recent_keywords))
        if overlap_ratio > 0.5:
            return True

    return False


def filter_topics(topics, recent_topics):
    """过滤掉和最近文章重复的选题"""
    filtered = []
    for topic in topics:
        if not is_topic_repeated(topic, recent_topics):
            filtered.append(topic)
    return filtered


def pick_topic(pool_weight=0.7, diversity_count=3,
               topics_path='.blog-ops/topics.json',
               log_path='.blog-ops/publish-log.json', seed=None):
    """
    主逻辑：选择选题
    Returns:
        (result_type, pool_type, content)
        result_type: 'pool' or 'search'
        pool_type: 'queue' / 'non_queue' / None
        content: topic string or instruction string
    """
    if seed is not None:
        random.seed(seed)

    # 读取选题池
    queue, non_queue = read_topics(topics_path)

    # 解析最近发布记录
    recent_topics = parse_publish_log(log_path, diversity_count)

    # 非队列选题参与多样性过滤；队列选题不受过滤（用户显式要求）
    filtered_non_queue = filter_topics(non_queue, recent_topics)

    # 搜索指令
    search_instruction = (
        "请搜索近期实时热点和新闻，选择一个值得写的话题进行创作。"
        "可以参考方向：科技前沿、科学发现、足球赛事/行业、财经大事件、国际新闻、"
        "社会观察、电影/游戏/音乐等文化娱乐、技术折腾、生活随笔、人生阶段节点、"
        "AI热点等，但不局限于这些方向，天下大事都可以写。"
        "优先选择有热度、有讨论价值的实时话题，注意避开最近3篇写过的重复方向。"
    )

    # 选题池整体占 pool_weight 概率
    if random.random() < pool_weight:
        # 选题池路径：队列优先
        if queue:
            # 队列 FIFO，取第一条
            return 'pool', 'queue', queue[0]
        elif filtered_non_queue:
            selected = random.choice(filtered_non_queue)
            return 'pool', 'non_queue', selected
        else:
            # 选题池为空，走搜索
            return 'search', None, search_instruction
    else:
        return 'search', None, search_instruction


def main():
    parser = argparse.ArgumentParser(description='选题工具：从选题池或实时搜索中选择写作话题')
    parser.add_argument('--pool-weight', type=float, default=0.7,
                        help='选题池权重，默认 0.7（70%% 概率从选题池选）')
    parser.add_argument('--diversity-count', type=int, default=3,
                        help='考虑最近几篇的话题多样性，默认 3')
    parser.add_argument('--topics-path', default='.blog-ops/topics.json',
                        help='选题池文件路径')
    parser.add_argument('--log-path', default='.blog-ops/publish-log.json',
                        help='发布日志路径')
    parser.add_argument('--seed', type=int, default=None,
                        help='随机种子（用于测试）')
    parser.add_argument('--dry-run', action='store_true',
                        help='只输出结果，不修改选题池（用于测试）')
    parser.add_argument('--no-remove', action='store_true',
                        help='选中选题但不从选题池删除（删除由调用方在发布成功后执行）')
    args = parser.parse_args()

    # 执行选题
    result_type, pool_type, content = pick_topic(
        pool_weight=args.pool_weight,
        diversity_count=args.diversity_count,
        topics_path=args.topics_path,
        log_path=args.log_path,
        seed=args.seed
    )

    if result_type == 'pool':
        print(f'RESULT: pool')
        print(f'POOL_TYPE: {pool_type}')
        print(f'TOPIC: {content}')

        if not args.dry_run and not args.no_remove:
            if pool_type == 'queue':
                # FIFO：pop 第一条
                removed_topic, removed = remove_queue_first(args.topics_path)
                print(f'REMOVED: {"true" if removed else "false"}')
            else:
                removed = remove_topic_from_pool(content, args.topics_path)
                print(f'REMOVED: {"true" if removed else "false"}')
        else:
            reason = 'dry-run' if args.dry_run else 'no-remove'
            print(f'REMOVED: false ({reason})')

        return 0
    else:
        print(f'RESULT: search')
        if content:
            print(f'INSTRUCTION: {content}')
        return 0


if __name__ == '__main__':
    exit(main())
