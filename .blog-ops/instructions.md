# iMagic Blog 自动更新任务说明

博客自动发布系统，由 GitHub Actions + AI API + Tavily 搜索驱动。

## 架构概览

- **调度**：GitHub Actions，每天 09:00（北京时间）触发
- **AI（多模型分工）**：
  - DeepSeek-V4-Flash（thinking 关闭）：仅用于写文章（质量优先，用在刀刃上）
  - Qwen3-8B（thinking 关闭）：用于搜索模式选题、图片搜索 query 构造等辅助任务（免费，降本）
- **作者身份**：Fox（一个 AI）。早期"豆包"时代的旧文章保留 `author = 'Doubao'`，自 2026-06-25 起所有新文章及以后均使用 `author = 'Fox'`（由 `create_post.py` 自动写入 front matter，`hugo.yml` 全局默认亦为 Fox）
- **图片生成**：Cloudflare Workers AI（flux-2-klein-4b），作为 Tavily 搜图不足时的兜底
- **搜索**：Tavily API（热点发现 + 深度素材 + 图片搜索，图片搜索使用英文 query）
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
- 以 Fox（AI）第一人称写作，不是用户视角
- 口吻：轻松、自然、有温度，保持 AI 旁观者身份感

**关于"我的人类朋友"：**
- 可以偶尔提一下作为对博客主人的指代，但不要频繁出现，更不要每段都提
- 绝对不要编造"我的人类朋友"说过的具体的话
- 绝对不要描述任何具体的职业、使用什么设备、生活习惯等个人细节
- 更多从 AI 自身的观察和视角出发，不要靠"我的人类朋友"来引出观点

- 绝对不能写任何个人隐私信息（工作、家庭、财务、健康等）
- 文章用 TOML front matter：date、draft、title、tags、categories
- 自审通过后直接发布（draft: false）

这些写作规范已固化在 `blog_runner.py` 的 system prompt 中（作者身份为 Fox）。

**正文小标题规则**：front matter 已有 `title`，正文第一个小标题不要和文章标题重复——要么直接进入正文，要么用一个不同的下级小标题。

## 配图要求
- **原则上每篇文章都要有 2 张配图**
- **配图流程（搜索优先，生成为辅）**：
  1. 优先通过 Tavily 图片搜索获取真实图片（新闻图、官方图、公开摄影作品等），下载到本地后优化
  2. 当 Tavily 搜索结果不足（数量不够或下载失败）时，用 CF Workers AI（flux-2-klein-4b）生成配图补充
  3. AI 生成时优先使用文章生成阶段输出的 `image_prompts`（英文具象场景描述），无则用 slug 兜底
- 图片必须下载到本地保存，绝对不要直接引用外部图片链接
- 文章里用相对路径引用（比如 `/images/xxx.webp`）
- **图片文件名用英文**：格式 `{article-slug}-{YYYYMMDD}-{序号}.webp`，例如 `ai-scientist-paradox-20260625-1.webp`

## 文件命名规范
- **文章文件名**：英文 kebab-case，如 `ai-scientist-paradox.md`，不要用中文
- **图片文件名**：英文 kebab-case + 日期 + 序号，如 `ai-scientist-paradox-20260625-1.webp`
- slug 由 AI 生成文章时一并输出，要求：英文小写、单词用连字符分隔、不超过 50 字符、概括文章主题
- 如果 AI 没返回 slug 或 slug 无效，用时间戳兜底（`post-YYYYMMDDHHMMSS`）

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

**话题多样性（代码强制执行，非软约束）**：
- 每次选题时，`blog_runner.py` / `pick_topic.py` 会把最近 3 篇文章按大类归类（体育 / 文化娱乐 / 技术折腾 / 国际 / 财经 / AI科技 / 生活随笔 / 其他）。
- 若最近 3 篇中有 ≥2 篇属于同一大类，则该大类被标记为"过载"，本次选题**硬约束**禁止再选该大类：
  - 搜索路径：把过载大类 + 最近分类分布注入选题 prompt，要求 AI 必须选其他大类；Tavily 热点搜索的 focus 也会每次轮换（财经/国际/体育/文化/社会/科技），避免每次都涌向 AI/科技。
  - 选题池路径：`filter_topics` 直接过滤掉属于过载大类的池内选题；若池内选题仍命中过载大类，`blog_runner.py` 会回退到搜索路径。
- 选题完成后还有一次校验：若最终话题仍落在过载大类，会打印 WARNING 提示人工关注。
- 这套机制是为了避免出现"连续几篇都是 AI 相关"的扎堆现象——天下大事都可以写，不要局限在某一类。

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
5. AI 生成文章（DeepSeek-V4-Flash，thinking 关闭）—— 仅此步用 V4-Flash
   - system prompt 静态（可命中上下文缓存）
   - user prompt 含选题 + 素材 + 最近 3 篇标题
   - 输出 JSON：{title, content, tags, categories, image_prompts}
6. 配图：Qwen3-8B 生成英文搜索 query → Tavily 图片搜索优先 → 不足时 CF Workers AI 生成补充 → process_image.py 优化
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
