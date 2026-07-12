# 📡 直播监控 + 多渠道推送

多平台直播状态监控工具，支持 B站 和 抖音，开播 / 新作品时自动推送通知。

## ✨ 功能特性

- 🎬 **多平台支持**：监控 B站 和 抖音 直播间
- 🔔 **多渠道推送**：Bark / Server酱 / 企业微信 / PushPlus / Telegram
- 📊 **直播时长统计**：记录开播时长、上次开播时间
- 📝 **历史日志**：保留最近 200 条状态变更记录
- 🔄 **合并推送**：多个主播同时开播时合并为一条通知
- 📱 **响应式页面**：手机端友好的监控页面
- 🎵 **新作品检测**：支持检测抖音新作品发布

## 📋 快速开始

### 1. 配置监控房间

编辑 `rooms.json` 文件：

```json
[
  {
    "platform": "bilibili",
    "id": "1874913653",
    "name": "峰哥亡命天涯"
  },
  {
    "platform": "douyin",
    "id": "83134194400",
    "name": "27～"
  }
]
```

### 2. 配置推送渠道

通过环境变量 `MONITOR_CONFIG` 配置：

```bash
export MONITOR_CONFIG='{"push": {"type": "bark", "url": "https://api.day.app/你的KEY"}}'
```

支持渠道：`bark` / `wecom` / `serverchan` / `pushplus` / `telegram`

### 3. 运行

```bash
# 检测一次直播状态
./run.sh

# 持续监控
./run.sh loop

# 检测新作品
./run.sh posts

# 检测全部
./run.sh all
```

## 🚀 部署

GitHub Actions + GitHub Pages（推荐）：

1. 在仓库 Secrets 中添加 `MONITOR_CONFIG`
2. 启用 GitHub Pages
3. 工作流自动每 5 分钟检测一次

## 📁 项目结构

```
new-monitor-project/
├── monitor.py           # 主监控脚本
├── push_utils.py        # 推送工具
├── check_status.py      # 直播状态检测
├── check_posts.py       # 新作品检测
├── common.py            # 通用工具
├── rooms.json           # 监控房间配置
├── monitor.html         # 监控页面
├── run.sh               # 运行脚本
├── .github/workflows/
│   └── check.yml        # GitHub Actions
└── README.md
```

## 📄 许可证

MIT License
