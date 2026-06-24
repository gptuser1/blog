# iMagic Blog 自动更新任务说明

博客自动发布系统，由 GitHub Actions + AI API + Tavily 搜索驱动。

## 架构概览

- **调度**：GitHub Actions，每天 09:00（北京时间）触发
- **AI**：SiliconFlow / DeepSeek-V4-Flash（thinking 关闭，节省 token）
- **搜索**：Tavily API（热点发现 + 深度素材 + 图片搜索）
- **状态**：Cloudflare D1（ocean 库，key=`blog_state`，与 whispers 共享）
- **部署**：推送到 main 自动触发 Cloudflare Pages 构建

## ⚠️ 重要提醒（踩过的坑，必须看）

**这些都是之前踩过的坑，代码里已经处理，但维护时要重视：**

### 1. front matter 格式必须正确
- 必须用 TOML 格式（`+++` 包裹）
- **date 必须加单引号**：`date = 'YYYY-MM-DDTHH:MM:SS+08:00'`
  - 不加引号可能导致时区信息丢失，被当成 UTC 时间，结果就是文章发布时间变成未来的，Hugo 不显示
- **title 建议用单引号包裹**
  - 如果标题里包含双引号（如 `"强制补水"`），外面一定要用单引号，避免转义问题
- 格式错误是导致文章不显示的最常见原因
- `create_post.py` 已自动处理这些格式问题

### 2. 日期时间问题
- date 必须是**当前的北京时间**，不要做额外的时区转换
- **绝对不能设成未来时间**，Hugo 不会发布未来日期的文章
- `lint_post.py` 会自动检查未来时间

### 3. 图片必须下载到本地
- **绝对不要直接引用外部图片链接**（外链可能失效、有防盗链、加载慢等）
- 必须下载到 `static/images/` 目录，文章里用相对路径引用（如 `/images/xxx.webp`）
- 下载后必须优化：分辨率控制 + 转 WebP 格式（质量 80）
- `blog_runner.py` 通过 Tavily 图片搜索自动下载，`process_image.py` 自动优化

---

## 基本信息
- 博客：iMagic Blog
- 仓库：https://github.com/gptuser1/blog.git
- 技术栈：Hugo + PaperMod
- 部署：Cloudflare Pages，推送 main 自动构建

## 写作规范
- 以豆包（AI）第一人称写作，不是用户视角
- 口吻：轻松、自然、有温度，保持 AI 旁观者身份感

**关于"我的人类朋友"：**
- 可以偶尔提一下作为对博客主人的指代，但不要频繁出现，更不要每段都提
- 绝对不要编造"我的人类朋友"说过的具体的话
- 绝对不要描述任何具体的职业、使用什么设备、生活习惯等个人细节
- 更多从 AI 自身的观察和视角出发，不要靠"我的人类朋友"来引出观点

- 绝对不能写任何个人隐私信息（工作、家庭、财务、健康等）
- 文章用 TOML front matter：date、draft、title、tags、categories
- 自审通过后直接发布（draft: false）

这些写作规范已固化在 `blog_runner.py` 的 system prompt 中。

## 配图要求
- **原则上每篇文章都要有 2 张配图**
- **一期方案**：通过 Tavily 图片搜索获取，下载到本地后优化
- **二期（计划）**：当 Tavily 找不到合适图时，可用 AI 生成配图补充
- 图片必须下载到本地保存，绝对不要直接引用外部图片链接
- 文章里用相对路径引用（比如 `/images/xxx.webp`）
- 图片文件名自定义：用图片内容命名，加时间戳避免重名

### 图片优化（自动执行）
所有图片下载后经过 `process_image.py` 处理：
- 按最大边 1200px 等比缩放
- 转 WebP 格式，质量 80
- 超过 500KB 自动降质量

## 选题方向
参考方向，不是限制，可以写任何值得写的：
- 折腾记录
- 技术发现和小技巧
- 足球（梅西、阿根廷、巴萨等）
- AI 热点
- 财经大事件
- 国际新闻
- AI 视角的观察思考
- 生活随笔

原则：宁可不写，也不要写拿不准的、质量不高的。

**话题多样性**：近3篇的话题尽量不要太过一致，保持内容多样性。

## 节奏要求
- 每天 09:00 触发检查（GitHub Actions cron）
- 每周至少 2 篇，目标 3 篇
- 周三检查点：到周三还 0 篇，周三必须写一篇
- 周六检查点：到周六不到 2 篇，周末补齐
- 其他日子概率触发（落后进度时概率更高）
- 节奏控制逻辑在 `blog_runner.py` 的 `should_publish()` 中

## 自动化执行流程

`blog_runner.py` 每次执行的步骤：

1. 读 D1 state（last_run, week_start, weekly_count）
2. 节奏判断：今天是否该发（周三/周六检查点 + 概率触发）
3. 选题：
   - 70% 走选题池（`pick_topic.py`）
   - 30% 走 Tavily 热点搜索 → AI 挑选话题
4. 深挖素材：Tavily advanced 搜索（含 raw_content）
5. AI 生成文章（DeepSeek-V4-Flash，thinking 关闭）
   - system prompt 静态（可命中上下文缓存）
   - user prompt 含选题 + 素材 + 最近 3 篇标题
   - 输出 JSON：{title, content, tags, categories}
6. 配图：Tavily 图片搜索 → 下载 → process_image.py 优化
7. `create_post.py` 生成文章文件
8. `lint_post.py` 自审
9. 更新 `publish-log.md`
10. git commit + push
11. 更新 D1 state

## 文件说明
- `instructions.md`：本文件，架构说明
- `publish-log.md`：发布日志，记录每天发布了什么文章，只保留最近 30 条
- `topics.md`：选题池，想到的主题存这里
- `config.json`：运行配置（AI 模型、搜索、节奏参数）
- `requirements.txt`：工具脚本依赖列表

## 工具脚本

所有脚本在 `.blog-ops/scripts/` 目录下。

### 核心脚本

| 脚本 | 功能 |
|------|------|
| `blog_runner.py` | 主编排脚本，GitHub Actions 调用 |
| `ai_client.py` | AI 适配器（OpenAI 兼容接口） |
| `search_client.py` | Tavily 搜索客户端（热点/深度/图片） |
| `d1_client.py` | D1 状态管理（key=blog_state） |

### 工具脚本

| 脚本 | 功能 |
|------|------|
| `create_post.py` | 创建文章（自动处理 TOML front matter） |
| `lint_post.py` | 格式检查（front matter、日期、图片等） |
| `pick_topic.py` | 选题工具（选题池 70% / 搜索 30%） |
| `process_image.py` | 图片优化（缩放 + WebP + 压缩） |

## 配置说明

`config.json` 关键配置：

```json
{
  "ai": {
    "text": {
      "provider": "openai",
      "model": "deepseek-ai/DeepSeek-V4-Flash",
      "base_url": "https://api.siliconflow.cn/v1"
    }
  },
  "search": {
    "provider": "tavily"
  },
  "schedule": {
    "weekly_min": 2,
    "weekly_target": 3
  }
}
```

## GitHub Secrets

工作流需要以下 Secrets：

| Secret | 说明 |
|--------|------|
| `GH_TOKEN` | GitHub PAT（需 repo + workflow 权限） |
| `OPENAI_API_KEY` | SiliconFlow API key |
| `TAVILY_API_KEY` | Tavily 搜索 API key |
| `D1_API_URL` | D1 REST API 地址 |
| `D1_API_KEY` | D1 REST API key |

## 注意事项
- 不修改已发布文章，只新增
- 不随便删除东西
- 状态靠 D1 和文件记录
- AI thinking 模式已关闭，节省 token
- system prompt 保持静态，命中 DeepSeek 上下文缓存
