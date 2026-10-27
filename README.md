# Discuz! 论坛每日签到自动化

基于 Discuz! X 系列（含 **X5.0**）的每日签到脚本，运行在 **GitHub Actions** 上，每天定时自动登录并签到。默认适配最常见的「DSU 每日签到」插件，也可通过配置适配其它签到插件。

## 目录结构

```
.
├── discuz_checkin.py          # 签到主脚本
├── requirements.txt           # Python 依赖
└── .github/workflows/checkin.yml   # GitHub Actions 定时任务
```

## 快速使用（GitHub Actions）

1. 把这个仓库 Fork 或推送到你自己的 GitHub 仓库。
2. 进入仓库 **Settings → Secrets and variables → Actions → New repository secret**，按需添加以下密钥：

| Secret | 说明 | 必填 |
| --- | --- | --- |
| `FORUM_URL` | 论坛根地址，如 `https://bbs.example.com` | ✅ |
| `DZ_USERNAME` | 登录用户名 | ✅ |
| `DZ_PASSWORD` | 登录密码 | ✅ |
| `DZ_QUESTION_ID` | 安全提问 id，无提问填 `0` | ⬜ |
| `DZ_ANSWER` | 安全提问答案 | ⬜ |
| `DZ_SIGN_URL` | 自定义签到页地址（见下方「适配其它插件」） | ⬜ |
| `DZ_MOOD` | 签到心情，如 `kua` | ⬜ |
| `DZ_TODAYSAY` | 签到留言 | ⬜ |
| `DZ_MIN_DELAY` / `DZ_MAX_DELAY` | 随机延迟区间（秒），避免所有用户同一秒请求 | ⬜ |
| `TG_BOT_TOKEN` / `TG_CHAT_ID` | Telegram 通知（可选） | ⬜ |
| `SCKEY` | Server 酱通知（可选） | ⬜ |

3. 进入 **Actions** 标签页，启用工作流；首次可点击 **Run workflow** 手动测试一次。
4. 之后每天由 `cron` 自动运行（默认北京时间 00:00）。

> ⚠️ 注意：公开仓库若 60 天无任何提交，GitHub 会自动禁用 scheduled workflow，届时需手动重新启用。

## 调整运行时间

工作流里的 cron 使用 **UTC**。北京时间 = UTC + 8。默认 `0 16 * * *` 即北京时间 00:00。

常见时间换算：

| 北京时间 | UTC cron |
| --- | --- |
| 00:00 | `0 16 * * *` |
| 08:00 | `0 0 * * *` |
| 08:30 | `30 0 * * *` |
| 12:00 | `0 4 * * *` |
| 21:00 | `0 13 * * *` |

## 适配其它签到插件

脚本默认访问 `plugin.php?id=dsu_paulsign:sign`（DSU 每日签到）。若你的论坛使用其它签到插件：

1. 在浏览器登录后，打开签到页面，复制其完整 URL。
2. 将其填到 `DZ_SIGN_URL` 这个 secret 里即可。

脚本会自动从该页面解析表单并提交；若返回内容不明确，会再次访问页面核验是否已签到。

## 本地运行 / 调试

```bash
pip install -r requirements.txt

# 方式一：环境变量
export FORUM_URL="https://bbs.example.com"
export DZ_USERNAME="yourname"
export DZ_PASSWORD="yourpass"
python discuz_checkin.py

# 方式二：命令行参数
python discuz_checkin.py --forum https://bbs.example.com --user yourname --pass yourpass
```

退出码：`0` 表示成功 / 已签到；非 `0` 表示失败（方便 CI 标记红色）。

## 局限与提示

- 仅适用于**登录不需要图形验证码**的论坛。若论坛启用了登录验证码，自动化登录会失败，需要另行处理。
- 不同 Discuz 版本 / 插件对签到接口、返回文案略有差异；如签到未生效，请先用本地 `--forum ...` 跑一次，根据日志调整 `DZ_SIGN_URL` 或 `DZ_MOOD` 等参数。
- 请遵守目标论坛的用户协议，仅用于个人账号的自动化，勿用于刷量等违规行为。
