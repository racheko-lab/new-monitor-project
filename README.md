# 📡 监控项目模板

监控类项目基础框架，可根据具体需求扩展功能。

## ✨ 功能特性

- 🎯 监控目标状态检测
- 🔔 多渠道推送通知（Bark / Server酱 / 企业微信 / PushPlus / Telegram）
- 📊 状态统计与历史记录
- 📱 响应式监控页面

## 📋 快速开始

### 1. 配置监控目标

编辑 `config.json` 文件，添加要监控的目标：

```json
{
  "targets": [
    {
      "id": "target-1",
      "name": "监控目标1",
      "url": "https://example.com"
    }
  ],
  "push": {}
}
```

### 2. 配置推送渠道（可选）

```json
{
  "push": {
    "type": "bark",
    "url": "https://api.day.app/你的KEY"
  }
}
```

支持的推送渠道：
- `bark` - Bark（iPhone）
- `wecom` - 企业微信群机器人
- `serverchan` - Server酱
- `pushplus` - PushPlus
- `telegram` - Telegram

### 3. 运行监控

```bash
# 安装依赖
pip install -r requirements.txt

# 执行一次检测
python monitor.py

# 持续监控（每60秒检测一次）
python monitor.py loop
```

## 🚀 部署方案

### GitHub Actions + GitHub Pages

1. Fork 本仓库
2. 在仓库 Settings → Secrets and variables → Actions 中添加 Secret：
   - Name: `MONITOR_CONFIG`
   - Value: `{"push": {"type": "bark", "url": "https://api.day.app/你的KEY"}}`
3. 启用 GitHub Pages：Settings → Pages → Source 选择 `GitHub Actions`

## 📁 项目结构

```
new-monitor-project/
├── monitor.py           # 监控主脚本
├── config.json          # 配置文件
├── status.json          # 当前状态（自动生成）
├── history.json         # 历史日志（自动生成）
├── requirements.txt     # 依赖列表
├── .github/workflows/
│   └── check.yml        # GitHub Actions 配置
└── README.md
```

## 🔧 技术栈

- **后端**: Python 3
- **部署**: GitHub Actions + GitHub Pages

## 📄 许可证

MIT License
