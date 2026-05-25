# 部署指南

## 三种场景,先选一种

| 场景 | 用什么 | 适合谁 |
|---|---|---|
| 本地常驻 + OS 服务管理 | `install-native.sh` | macOS/Linux 用户,要最轻量、零额外依赖 |
| 本地常驻 + Docker 隔离 | `docker-compose.yml` | 已经在用 Docker、想跨机器迁移、想跟系统 Python 隔离 |
| 局域网 / 远程访问 | 见末尾"远程访问"章节 | 想从手机/平板访问驾驶舱 |

**云服务器部署不推荐**:数据私密性、成本、维护负担都不划算,纯自用工具就在本地跑。

---

## 场景 1:原生部署(推荐)

### 一键安装

```bash
cd rl-agent-tutor
bash deploy/install-native.sh
```

脚本会自动:
1. 在项目下建 `.venv` 并 `pip install -e .`
2. 检测 macOS / Linux,装对应的服务文件
3. 替换路径占位符
4. 加载 / enable Web UI 和 daemon 两个服务
5. macOS 走 launchd,Linux 走 systemd user service

完成后浏览器打开 `http://127.0.0.1:8765` 就能用。**重启电脑后服务自动起,关掉终端不影响**。

### 第一次运行前

`.env` 文件要先填好 API key,不然服务起来后调 LLM 会立刻报错:

```bash
cp .env.example .env
# 编辑 .env,填入 ANTHROPIC_API_KEY 或 OPENROUTER_API_KEY
```

### 管理命令

**macOS:**

```bash
# 查看状态
launchctl list | grep rlagent

# 看日志
tail -f ~/Library/Logs/rl-agent-tutor/web.err.log
tail -f ~/Library/Logs/rl-agent-tutor/daemon.err.log

# 停止
launchctl unload -w ~/Library/LaunchAgents/com.rlagent.web.plist
launchctl unload -w ~/Library/LaunchAgents/com.rlagent.daemon.plist

# 重新启动(改了代码后)
launchctl unload -w ~/Library/LaunchAgents/com.rlagent.web.plist
launchctl load   -w ~/Library/LaunchAgents/com.rlagent.web.plist
```

**Linux:**

```bash
# 状态
systemctl --user status rl-agent-web rl-agent-daemon

# 日志(实时)
journalctl --user -u rl-agent-web -f
journalctl --user -u rl-agent-daemon -f

# 停止 / 启动 / 重启
systemctl --user stop rl-agent-web
systemctl --user start rl-agent-web
systemctl --user restart rl-agent-web

# 让服务在你登出后继续跑(只需做一次)
sudo loginctl enable-linger $USER
```

### 升级流程

代码改了之后:

```bash
cd rl-agent-tutor
git pull                   # 或者自己拷新文件
.venv/bin/pip install -e . # 如果加了新依赖

# macOS
launchctl unload -w ~/Library/LaunchAgents/com.rlagent.web.plist
launchctl load   -w ~/Library/LaunchAgents/com.rlagent.web.plist

# Linux
systemctl --user restart rl-agent-web rl-agent-daemon
```

---

## 场景 2:Docker 部署

### 启动

```bash
cd rl-agent-tutor
cp .env.example .env  # 填好 API key

docker compose -f deploy/docker-compose.yml up -d --build
```

第一次构建大约 2-3 分钟(主要是装 pymupdf 和它的编译依赖)。

### 管理

```bash
# 看日志
docker compose -f deploy/docker-compose.yml logs -f web
docker compose -f deploy/docker-compose.yml logs -f daemon

# 停止
docker compose -f deploy/docker-compose.yml down

# 升级(代码改了)
docker compose -f deploy/docker-compose.yml up -d --build

# 进容器调试
docker compose -f deploy/docker-compose.yml exec web bash
```

### Docker 方案的几个细节

**`workspace/` 目录用 host 挂载**:你的 PDF、笔记、计划全在主机的 `./workspace/` 里,删容器不会丢数据。

**端口绑定 127.0.0.1:8765**:外部访问不到。要 LAN 访问见下一节。

**两容器共享一个 image**:web 和 daemon 复用同一份代码,改 command 启不同进程。镜像大约 800 MB(主要是 PyTorch 系生态没装,pymupdf 不算大)。

---

## 场景 3:局域网 / 远程访问

如果你想在手机、平板、其他电脑上也用驾驶舱,需要做几件事:

### 局域网访问(同一 Wi-Fi)

最简单。把 host 从 `127.0.0.1` 改成 `0.0.0.0`:

**原生部署**:编辑 `~/Library/LaunchAgents/com.rlagent.web.plist`,把 `--host` 后的 `127.0.0.1` 改成 `0.0.0.0`,然后重新 load。

**Docker**:`docker-compose.yml` 里 `ports` 改成 `- "8765:8765"`(去掉 `127.0.0.1:`),重启。

然后在手机浏览器输入主机的 LAN IP,例如 `http://192.168.1.10:8765`。

⚠️ **加一层认证**:这个应用现在没有任何登录机制,LAN 暴露后任何人在你网络里都能用你的 API key 调 LLM。建议在前面套一层 nginx basic auth,或者直接用 Tailscale / Cloudflare Tunnel。

### 远程公网访问(不在同一网络)

最简单不折腾的方案:**Tailscale**。装客户端到主机和你的手机,自动组 mesh VPN,然后用主机的 Tailscale IP 访问。零配置 HTTPS、零端口暴露、私有。

```bash
# Mac/Linux 主机
brew install tailscale  # 或 curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up

# 手机装 Tailscale app,登同一账号
# 然后在手机浏览器: http://<主机的-tailscale-ip>:8765
```

替代方案有 ngrok / Cloudflare Tunnel,但 Tailscale 在私人自用场景体验最好。

---

## 验证清单

部署完后这几件事要全 ✓:

- [ ] `curl http://127.0.0.1:8765/api/health` 返回 `{"ok":true,"provider":"..."}`
- [ ] 浏览器打开首页能看到 metaLine 上的 provider 信息
- [ ] 能创建 plan、能 ask、能 fetch
- [ ] 关掉所有终端窗口,等 30 秒,刷新页面,Web UI 仍可访问
- [ ] 重启电脑,登入后无操作 1-2 分钟,Web UI 自动可访问
- [ ] `tests/smoke_test.py` 在已部署的 venv 里能跑过

---

## 故障排查

**Web 起不来,日志报 `ANTHROPIC_API_KEY not set`**:`.env` 没找到。原生部署时检查 plist/service 的 `WorkingDirectory` 是否指向项目根;Docker 时检查 `env_file: ../.env` 路径。

**`launchctl load` 报 `Bootstrap failed: 5: Input/output error`**:plist 路径里有 typo。`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.rlagent.web.plist` 看具体错。

**systemd 服务起来后立刻 `Active: inactive (dead)`**:`journalctl --user -u rl-agent-web -n 50` 看具体错。最常见是 `.env` 路径或 venv 路径写错。

**Docker build 在 pymupdf 阶段卡很久**:正常,pymupdf 在 slim 镜像里要从源码编译。耐心等 1-2 分钟,或者把基础镜像换成 `python:3.11`(去掉 `-slim`),编译会快但镜像大。

**端口 8765 被占用**:换端口,plist/service/compose 里都改成同一个新端口。

**Mac 上桌面通知不弹**:系统设置 → 通知 → 找 `osascript` 或终端 app,允许通知权限。
