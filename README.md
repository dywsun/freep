# Relay

基于 sing-box 的单服务器多用户管理后台。每种协议一个固定端口，用户共用入口、使用各自独立凭据。优先支持 VMess WS 与 TUIC v5，另外提供 VLESS Reality/Vision、Hysteria2、AnyTLS。

当前为首个实现版本。前端原型与真实后台分开：直接静态托管 `frontend/` 是模拟预览；由 `backend/app.py serve` 提供页面时启用真实登录和 API。真实后台没有演示账户或硬编码密码。

## 一行安装

将整个项目上传至 `dywsun/freep` 仓库的 `main` 分支后，在 VPS 的 **root 终端**执行：

```bash
bash <(curl -fLs https://raw.githubusercontent.com/dywsun/freep/main/install.sh)
```

执行前，在 Cloudflare 将 `free.dywsun.dpdns.org` 的 A 记录指向 VPS 公网 IPv4，设置为灰云“仅 DNS”，并在云安全组放行 `80/TCP`、`18898/TCP`、`8880/TCP` 和 `32786/UDP`。安装时按提示输入管理员账号、密码和后台路径（例如 `/freedom-network`）。

默认后台地址示例：`https://free.dywsun.dpdns.org:18898/freedom-network/`。安装器自动获取源码提交 SHA，无需手动填写；网站证书申请失败时会停止，不降级为 HTTP。

## 首次安装

主目标为全新 Ubuntu 22.04 LTS（也提供 Debian 12+、CentOS 7/8/Stream 9/10 安装分支）。Ubuntu/新系统支持 amd64/arm64；CentOS 7/8 兼容分支仅支持 x86_64。需要 systemd。建议使用干净 VPS。安装器不会执行原 sb.sh，不会清空防火墙、停止已有 Apache 或重写其他 Nginx 站点。不是原脚本完整功能的移植，不包含 WARP、Argo、TG 推送。

从你自己的仓库下载固定提交版本，阅读后在源码目录运行：

```bash
export PUBLIC_HOST=free.dywsun.dpdns.org
export WEB_PORT=18898
export VMESS_PORT=8880
export TUIC_PORT=32786
export VLESS_PORT=10443
export HYSTERIA2_PORT=10444
export ANYTLS_PORT=10446
# 网站默认自动向 Let's Encrypt 申请可信 HTTPS 证书。
# 可选通知邮箱，不设置也不会要求手动输入证书。
export ACME_EMAIL=you@example.com
# 仅当已经持有匹配域名、受信任的完整证书链时，才设置下面两项：
# export WEB_TLS_CERT=/root/certs/fullchain.pem
# export WEB_TLS_KEY=/root/certs/privkey.pem
# 原脚本协议默认值（可以覆盖）
export TLS_SERVER_NAME=www.bing.com
export REALITY_SNI=apple.com
export VMESS_TLS=false
# VMESS_WS_PATH 不设置时生成共享的 UUID-vm 形式路径。
# 节点需要改用已有证书时，另设 TLS_CERT 和 TLS_KEY。
sudo --preserve-env=PUBLIC_HOST,WEB_PORT,VMESS_PORT,TUIC_PORT,VLESS_PORT,HYSTERIA2_PORT,ANYTLS_PORT,ACME_EMAIL,WEB_TLS_CERT,WEB_TLS_KEY,TLS_SERVER_NAME,REALITY_SNI,VMESS_TLS bash install.sh
```

已经在 root shell 中时，直接 `bash install.sh` 即可。

脚本首先要求输入管理员账号、隐藏输入密码并二次确认，以及自定义后台路径（如 `/freedom-network`），然后才开始安装。路径必填，支持多级路径，仅允许字母、数字、短横线、下划线，以 `/` 开头且不能以 `/` 结尾。路径由脚本运行时提示输入，不写死为默认值。账号 3–32 位字母/数字/_/-，密码 12–256 个字符，无默认密码。密码通过 stdin 传递给初始化程序，不放进命令行、环境变量或明文临时文件。数据库使用 PBKDF2-SHA256（600000 次）保存管理员密码哈希。

端口来自环境变量或脚本顶部默认值，不交互询问、不随机替换。端口冲突、占用或无效会退出。API 18090 与统计 API 18091 固定绑定 127.0.0.1，不能与公开端口冲突。默认只启用 VMess、TUIC；没有用户时不创建代理监听。

默认仓库为 `dywsun/freep`，默认分支 `main`。

安装器会自动把 main 解析为具体提交 SHA，再按该提交下载前端、后端和其他安装文件，无需手动填写 SHA。SHA 是某次提交的唯一编号，用于版本定位，不是密码或令牌。仓库为空、GitHub API 限流或版本解析失败时停止安装。仍可通过 `RELAY_REPO=owner/repo` 和 `RELAY_REF=40位提交SHA或分支/标签` 覆盖默认来源。

### 内核与证书

默认固定 sing-box **1.14.4**。优先复用本机匹配的统计内核，其次下载本仓库经过 SHA256 与版本/功能检查的预编译包；没有对应发布时才使用官方同版本源码及校验后的 Go 工具链编译。首次 GitHub 发布完成后，通常无需在 VPS 上安装 Go 或编译。详见下方「加速安装」。

协议默认参数参考原 sb.sh：

| 项目 | 默认值 |
|---|---|
| Reality SNI / 握手目标 | `apple.com` / `apple.com:443` |
| VMess | WS，不启用 TLS；共享路径为生成的 `UUID-vm`；early data 2048，头 `Sec-WebSocket-Protocol` |
| 节点证书 | `prime256v1` EC 自签，CN=`www.bing.com`，36500 天 |
| HY2 | TLS + `h3`，`ignore_client_bandwidth=false` |
| TUIC v5 | TLS + `h3`，BBR |
| AnyTLS | TLS |

端口与用户凭据不复制原脚本的随机端口和全协议共用 UUID：端口按环境变量固定，凭据按用户/协议独立。节点证书可通过 `TLS_CERT/TLS_KEY` 替换，SNI 用 `TLS_SERVER_NAME`；Reality 握手还可用 `REALITY_HANDSHAKE_HOST/REALITY_HANDSHAKE_PORT`，WS 路径用 `VMESS_WS_PATH`，TUIC 拥塞控制用 `TUIC_CONGESTION_CONTROL`。设置受信任节点证书时，应同时设置匹配的 TLS_SERVER_NAME；VMess 需要 TLS 则设 VMESS_TLS=true。

### 资源监控

侧栏保留概览、用户管理、协议入口、订阅管理、资源监控；移除没有实际用途的个人工作空间、分流设置、系统设置入口。

资源监控读取运行管理后端这台机器的真实数据，每 5 秒采样并自动更新：CPU 使用率和逻辑核心数、1/5/15 分钟系统负载、内存使用/可用量、根文件系统空间占用、系统磁盘读写速率、网卡收发速率和累计字节。保留最近 5 分钟趋势（内存中，后台重启后重新积累）。本地预览显示本机资源，并明确标注不是 VPS。

网络默认优先显示 Linux 默认路由接口，不把虚拟接口全部相加，列表可查看各网卡。网卡流量包含整机服务，与 sing-box 用户用量不同。未取得网卡带宽上限时不展示虚假的网络利用率百分比；磁盘空间占用不等于 I/O 忙碌率。首次采样需要等待下一周期形成速率。

### 网站 HTTPS、域名和自定义路径

网站默认域名为 `free.dywsun.dpdns.org`（可用 PUBLIC_HOST 覆盖）。运行安装器之前，在 Cloudflare 创建指向 VPS 公网 IPv4 的 A 记录，设置为 **仅 DNS / 灰云**，等待解析生效；没有可用 IPv6 时不要配置 AAAA。当前默认 18898 不是 Cloudflare 普通橙云代理支持的 HTTPS 端口。VPS 云安全组放行 TCP 80 和 WEB_PORT。

默认自动申请 Let's Encrypt 证书，固定使用 acme.sh 3.1.7 的 webroot 模式：

1. 安装前输入管理员及后台路径，例如 `/freedom-network`。
2. Nginx 在公网 80 端口仅提供 `/.well-known/acme-challenge/` 文件；其他请求返回 404，不代理后台。
3. 检查域名 A 记录和验证文件可达性，发起 ACME 验证。
4. 校验签发证书的系统信任链、域名、剩余有效期和私钥匹配关系。
5. 成功后配置 HTTPS，启动后台并做本机 HTTPS 检查。申请失败停止安装，不生成自签网站证书、不开放明文后台。

若输入 `/freedom-network`，默认管理地址为：

```text
https://free.dywsun.dpdns.org:18898/freedom-network/
```

路径外的 `/`、`/api/`、`/sub/` 等均不开放；路径本身不替代 HTTPS、密码和 CSRF。静态资源、管理 API、用户订阅 URL、登录 Cookie 路径全部适配所选前缀。80 端口不重定向到隐蔽路径，避免泄露入口；它需保留用于自动续期。

`relay-acme.timer` 每天两次检查续期，成功后通过固定 root 部署脚本检查新证书，更新网站证书并执行 `nginx -t && systemctl reload nginx`，失败尝试恢复旧网站证书。续期不重启 sing-box、不改变节点证书/SNI。

网站证书部署到 `/etc/relay/web-cert.pem`、`web-key.pem`，ACME 账户保存在 `/etc/relay/acme`，验证目录 `/var/lib/relay-acme`。节点证书仍为 `/etc/relay/node-cert.pem`、`node-key.pem`，保留原脚本默认自签规则。指定已有 `WEB_TLS_CERT/WEB_TLS_KEY` 时也必须通过信任链和域名检查，这种导入模式由证书提供方负责续期。

验证自动续期状态：

```bash
systemctl list-timers relay-acme.timer
journalctl -u relay-acme.service --no-pager -n 100
```

本地测试覆盖路径和生成配置；真实签发需要上述 DNS、云安全组及公网连通性，在对应 VPS 安装时完成。

CentOS 7/8 通过独立 yum 配置使用 CentOS Vault/EPEL 归档，不覆盖现有 repo；缺少 Python 3.9+ 时通过校验后的 uv 安装独立 Python 3.12，不替换系统 Python。SELinux 保留启用，给网站/API 端口标注 HTTP 类型并允许 Nginx 反向代理。CentOS 7/8 已结束常规支持，兼容分支不代表恢复系统安全维护，且尚未完成真实 VPS 安装验收。

云安全组需放行证书验证 TCP 80、网站 TCP、VMess/VLESS/AnyTLS TCP、TUIC/Hysteria2 UDP 对应端口。检测到 UFW 正在运行时只增添这些允许规则。firewalld 正在运行时添加对应运行时和永久端口规则；其他防火墙交由现有管理方式处理，不清空规则。

## 管理功能

- 管理员登录/退出：HttpOnly + SameSite=Strict Cookie，HTTPS 下 Secure；八小时会话；Origin + CSRF 验证；登录失败节流。
- 用户：创建、启用/停用、协议权限分配、单协议凭据重置、专属订阅令牌重置。
- VMess/VLESS 使用 UUID，TUIC v5 使用 UUID + 密码，HY2/AnyTLS 使用独立密码；凭据按用户、按协议独立生成。
- 协议：固定端口编辑、全局启用/停用；所有用户共享入口。
- 订阅只提供节点，不包含分流规则、策略组或本地监听配置。界面提供通用节点订阅（v2rayN / v2rayNG / Karing，Base64 链接集合）与 Clash / Mihomo 节点订阅（只有 `proxies`，JSON 形式的 YAML，可作为 `proxy-providers` 来源）。旧 `karing` 格式保留为通用格式别名；旧 `singbox` 地址仅返回节点 `outbounds` 片段，不是完整客户端配置。
- 所有客户端必须按具体版本验证。订阅转换并不意味着所有客户端支持全部协议。
- 管理操作有只记录动作、不含凭据的审计日志，可登录后请求 `/api/audit`。

## 二维码分享

订阅管理提供每种客户端格式的“订阅二维码”；用户详情的“节点二维码”可以选择单个获准使用的协议。支持显示二维码、复制原始链接、下载 PNG。

二维码使用随网站打包的 qrcode-generator 2.0.4，在浏览器 Canvas 本地生成，不访问第三方二维码 API 或 CDN。单节点链接复用服务端订阅生成逻辑，经管理员登录后获取，只返回当前有效用户、已启用入口的独立凭据。订阅二维码编码的是订阅 URL，单节点二维码编码的是 vmess://、tuic:// 等分享 URI；客户端能否扫码导入取决于它对相应格式和协议的支持。

二维码包含访问凭据，请只发给对应用户。重置订阅令牌使旧订阅二维码失效；若要让已下载的节点或单节点二维码失效，还需重置相应协议凭据。静态前端的二维码仅供演示，不能连接真实节点。

## 配置应用和权限

HTTP 服务运行身份为 `relay-panel`，只能通过 sudo 调用 root 所有、固定路径的 `backend/apply.py`。辅助程序再次验证协议、端口、凭据、用户数量，使用固定证书与配置路径，不能传任意命令或文件路径。

操作顺序：串行修改 → 生成临时配置 → `sing-box check` → 原子替换 → 重启 `relay-sing-box` → 检查运行状态；失败尝试恢复旧配置；成功才保存用户状态。带 revision 的乐观锁避免陈旧页面覆盖新数据。

**所有协议使用一个实例，应用用户/入口变更会短暂断线，并非无断线热更新。** 数据库与外部进程无法做到单一原子事务，崩溃窗口中可能临时不一致；后台服务启动时会根据已提交数据库重新生成配置。

## 流量与额度

使用 sing-box V2Ray gRPC StatsService，`users[].name` 采用 `用户ID:协议`。VMess/TUIC 将认证后的用户名称传入连接元数据，采集该用户的 TCP/UDP 上下行计数。后台每 10 秒读取不重置的远端计数，SQLite 保存增量，并按 systemd 进程启动单调时间戳 区分内核重启。原始用户计数按协议存储，页面分别展示每位用户本月上行、下行、合计及额度；概览展示本月上下行卡片，以及最近 24 小时的两条独立小时流量曲线。

后端每 10 秒采集一次，页面登录后每 5 秒自动读取仅含统计数据的接口，不需要手动刷新。正常情况下有约 10–15 秒显示延迟，属于近实时显示，不是逐秒网速。后台标签页隐藏时暂停读取，回到页面立即更新；退出登录停止轮询，网络错误保留旧值并提示。更新只替换统计区域，不重载页面或打断表单，并保留“刷新统计”按钮。概览、用户列表、CSV 导出均区分上下行，按上海时区自然月统计。

上行=客户端到代理服务器，下行=服务器到客户端。这里是内核记录的代理流量，不含全部 TLS/QUIC、TCP/IP 开销，不等同于网卡字节或云厂商账单。采集故障会明确显示状态；突发断电/内核崩溃会丢失最后一个采样周期的数据，不适合严格计费。

按上海时区计算自然月和到期日（到期日当天仍可用）。到期或达到月额度后，采样任务移除用户并应用配置，订阅即时拒绝下载。强制应用会影响同实例所有用户；不是单连接级无损踢人，最多有采样和应用延迟。额度不是精确实时限速/计费。

## 运维

```bash
sudo bash install.sh status
sudo bash install.sh backup
sudo bash install.sh reset-password
sudo journalctl -u relay-panel -u relay-sing-box --no-pager -n 100
```

备份会短暂停止管理后台，打包 `/etc/relay` 与 `/var/lib/relay`，代理仍继续运行。文件含私钥、用户凭据、订阅令牌，权限为 root 私有。恢复需在停服后恢复这两个目录，并恢复 relay-panel 对数据目录的所有权。首版尚不提供自动升级、自动恢复或卸载命令；重复安装会拒绝覆盖已有部署。不要直接覆盖数据库或运行原 sb.sh 管理这套配置。

Nginx 配置在 `/etc/nginx/conf.d/relay.conf`；源码及 venv 在 `/opt/relay`；数据在 `/var/lib/relay`；root 配置和证书在 `/etc/relay`。

## 前端热更新

支持只切换网站页面，不重启管理后台、Nginx 或 sing-box，不修改用户数据库、节点凭据和证书。首次使用这一功能必须先安装包含版本化静态资源处理的后端；旧版后端不能只替换网页就获得新增的资源监控 API。

将代码推送 GitHub 后，在运行兼容后端的 VPS 执行最新安装入口的更新命令：

```bash
bash <(curl -fLs https://raw.githubusercontent.com/dywsun/freep/main/install.sh) update-web
```

也可直接执行已安装工具：

```bash
/opt/relay/venv/bin/python /opt/relay/scripts/update_frontend.py
```

默认将 main 解析为固定提交，下载到暂存目录，检查文件完整性和 `frontend/manifest.json` 中的 API 兼容版本，然后原子切换 `/opt/relay/web-current`。版本目录保存在 `/opt/relay/web-releases/提交SHA`；原页面引用带版本号的静态资源，避免一次加载混用新旧 JS/CSS。更新失败不切换当前版本。VPS 如果安装了 Node，还会检查 JS 语法；仓库 CI 应先完成完整前端检查。

已打开的页面每 30 秒检查页面版本，发现新版本显示“页面有更新 · 刷新”，由用户点击，不强制刷新填写中的表单。需要回退到保留版本时：

```bash
/opt/relay/venv/bin/python /opt/relay/scripts/update_frontend.py --rollback 目标版本40位SHA
```

这不是完整后端/内核升级工具。后端接口发生不兼容变化时会拒绝热更新，需要先部署对应后端版本。

## 本地开发

```bash
python3 scripts/dev.py
# 按提示设置本地管理员，访问 http://127.0.0.1:18092
```

开发模式无需 root、Nginx 或 sing-box；SQLite/API/认证和订阅是真实逻辑，但不会启动代理或伪造统计数据。

```bash
python3 -m unittest discover -s tests -v
node --check frontend/app.js
node --check frontend/live.js
node --check frontend/share.js
node tests/test_qr.cjs
node tests/test_traffic.cjs
node --check frontend/monitor.js
bash -n install.sh scripts/build-sing-box.sh
```

可选真实内核测试：设置 `SING_BOX_BIN=/absolute/path/to/sing-box` 后执行 `python3 scripts/check_configs.py`。该脚本需要本地 openssl，校验全部服务端入口及 sing-box 客户端配置，不修改系统配置。

## 来源

安装流程参考 [sing-box-yg](https://github.com/yonggekkk/sing-box-yg)，本仓库未复制执行其完整脚本。内核、统计接口与协议配置依据 [sing-box 官方文档](https://sing-box.sagernet.org/) 和对应固定版本源码。第三方内核及依赖保留各自许可证。

## 已执行验证与边界

本地已使用官方 1.14.4 源码构建统计内核，完成 VMess/TUIC 双用户的 TCP + UDP 回环实测和四组用户/协议独立上下行计数验证。`scripts/smoke_protocols.py` 可复现（需 requirements 与 SING_BOX_BIN）。五种协议服务端与 sing-box 客户端配置均经真实内核 check。Ubuntu/CentOS 的包管理、Nginx/SELinux/systemd 整机部署仍需在对应干净 VPS 验收；macOS 本机测试不能替代该步骤。

网站自动证书机制依据 [acme.sh 文档](https://github.com/acmesh-official/acme.sh) 和 [Let’s Encrypt HTTP-01 说明](https://letsencrypt.org/docs/challenge-types/)。Cloudflare 代理端口见 [官方端口列表](https://developers.cloudflare.com/fundamentals/reference/network-ports/)。

## 安装中断：内核下载后出现 curl 404

早期安装器错误引用了不存在的独立校验文件。当前已改为读取 GitHub Releases API 的资产 `digest`（SHA256）并验证实际下载文件，缺少摘要或不匹配时拒绝继续。

如果中断发生在这一阶段（依赖安装成功，但尚未初始化管理员数据库和服务），将最新完整项目上传 main 分支后，重新执行上方一行安装命令即可，通常无需重装系统或删除已安装依赖。若提示已有部署，不要删除数据库，应先确认已有服务和数据。

## Relay Worker 订阅网关

单个 Worker 可服务多台独立 VPS。仅保存 UUID、公网 IP、回源 URL、管理密钥哈希等绑定数据；订阅实时由 VPS 生成，不上传或缓存用户快照。注册必须验证注册令牌，后续更新必须验证该 VPS 的独立管理密钥。

## 手动部署一次

1. 在 Cloudflare 控制台创建 D1 数据库，例如 `relay-gateway`。
2. 打开 D1 的 Console，执行本目录 `schema.sql` 的全部 SQL。
3. 创建 Worker，例如 `relay-subscriptions`。将 `dist/worker.js` 的全部内容粘贴到代码编辑器，保存并部署。此单文件已包含网站，不需要另外部署 Pages。
4. 在 Worker Settings → Bindings 中绑定 D1，变量名必须为 `DB`，选择上面的数据库。
5. Compatibility date 设置为 `2026-11-22`，Compatibility flags 添加 `nodejs_compat`。不设置则 `node:net` 无法加载。
6. 在 Domains & Routes 添加 Custom Domain：`subp.dywsun.dpdns.org`。该域名需属于当前账户的有效 Cloudflare Zone，不能有冲突 CNAME。无需设置指向 VPS 的 A 记录。
7. 关闭 Worker invocation logs / observability，避免记录包含用户令牌的订阅 URL。本项目配置默认关闭。
8. 打开该域名，首次为固定账号 **dywsun** 设置密码（12–256 字符，再次确认）。首次设置无需初始化令牌；按用户要求使用先到先设置。数据库已有管理员后无法再次初始化，竞争初始化只有一个请求成功。
9. 登录 → 注册设置 → 随机生成并保存注册令牌（24–256 位）。可以暂停新注册或更换令牌，不影响已注册 VPS。

随后，每台 VPS 在网页「订阅入口设置」填写 Worker URL 和注册令牌，并点击注册。名称与公网 IP 可自动获取，也可手动填写；默认回源为 `https://本机域名:8443/后台路径/sub`。UUID 和独立管理密钥自动生成并保存在 VPS 的 `gateway.json`（0600），注册令牌不保存。切换订阅入口为 Worker 后，链接形如：

```text
https://subp.dywsun.dpdns.org/sub/<VPS-UUID>/<用户令牌>?format=uri
```

新安装器同时配置 Nginx **8443 HTTPS 订阅回源入口**，只代理 `后台路径/sub/` 的 GET/HEAD。管理后台仍在 18898，8443 不提供后台。需在 VPS 供应商安全组放行 8443/TCP，并保留证书续期使用的 80/TCP。旧版本需要升级后端与 Nginx 配置后再接入。自定义回源必须是公网 DNS 域名、受信任证书、443 或 8443，不允许私网/IP 字面量/重定向。不要将回源指向 Worker 域名。

## 管理与认证

- 管理 API 全部需要 Secure/HttpOnly/SameSite=Strict 会话 Cookie，写入操作另需同源 Origin 和 CSRF Token。
- 密码使用 PBKDF2-HMAC-SHA256（100,000 次，随机盐）；D1 不保存明文密码、注册令牌和 VPS 管理密钥。
- 账户安全页修改密码需验证原密码；修改后全部旧会话失效，需要重新登录。会话最长 8 小时。
- 登录、初始化、改密与注册有按 IP 的请求频率限制。高流量环境可额外配置 Cloudflare WAF 限速；不要给整个订阅域名添加交互式挑战，否则客户端可能无法导入。
- 禁用 VPS 后立即拒绝新的 Workers 订阅请求；即使回源期间并发禁用，也会在发送响应前再次检查绑定。已发送的响应无法撤回。
- 删除绑定同时撤销独立管理密钥。无法凭注册令牌覆盖同 UUID 不同 IP/回源/管理密钥的绑定；合法改 IP 使用该 VPS 的独立密钥更新。
- 注册 IP 是机器提交的公网 IP，面板用来定位，**不是认证凭据或由 Worker 探测验证的在线状态**。多 VPS 绑定不会互相覆盖。
- 只有订阅接口会回源；不转发浏览器 Cookie、管理员凭据或任意目标参数，不缓存订阅。D1 读取使用 first-primary 会话，避免禁用后读取旧状态。
- 回源失败返回错误且不删除绑定。不会停用实际节点或本机订阅；用户到期和流量额度仍由 VPS 执行。

## 更新与本地验证

修改前端或 Worker 源码后执行 `python3 scripts/build_worker.py`（仓库根目录），重新上传生成的 `dist/worker.js`；复用原 D1，账号、注册令牌与绑定保留。更新前务必备份 D1。不要执行删除管理员/绑定的 SQL。

本地需要 Node 22.13+（内置 SQLite）：

```bash
python3 scripts/build_worker.py
node scripts/worker_preview.mjs
```

打开 `http://127.0.0.1:18094/`，本机数据在 `.local/worker-gateway-preview.db`。该预览使用真实 API/哈希/数据库，但不是部署到 Cloudflare。请使用独立测试密码。忘记生产密码时，只能由 Cloudflare 管理员通过 D1 清除会话并重置管理员后重新初始化；没有公开密码找回接口。

当前已做 Node + SQLite 接口测试，尚未使用真实 Cloudflare 账户部署验收。Workers Free 的 CPU/请求配额可能影响大量登录或订阅请求，具体以控制台套餐限制为准。

## 加速安装：预编译统计内核

安装器不再先下载官方内核再临时编译。默认按以下顺序安装与 `SB_VERSION` 一致且包含 `with_quic / with_utls / with_v2ray_api` 的统计内核：

1. 复用本机已经存在的匹配内核。
2. 下载本仓库 GitHub Releases 的预编译 Linux amd64 / arm64 内核，使用 GitHub 发布记录中的 SHA256 校验后，再验证版本和功能标签。
3. 发布不存在或暂时无法读取时，回退为本机源码编译；若下载文件校验失败则立即停止，不跳过校验或悄悄回退。

首次启用需要将新工作流推送至 GitHub，然后进入仓库 **Actions → Build statistics kernel → Run workflow**。默认版本为 `1.14.4`；两个架构分别在原生 Linux runner 构建、验证，共同发布到 `sb-stat-v1.14.4-go1.26.10-r1`。工作流相关文件推送 main 时也自动触发。后续安装只下载内核，不再下载 Go 和编译依赖，具体时间取决于网络与其他系统依赖、证书申请。项目预编译包不是 SagerNet 官方包。

工作流缓存 Go 模块和构建产物；已完整发布的同版本包不会重新覆盖。若中断留下不完整 draft，先在 Releases 检查该草稿再重试。改变功能标签/编译配方时必须增加发布修订号并同步修改安装器标签，避免同名版本内容漂移。

可在执行脚本前设置：

```bash
# 仅允许预编译包，不可用就提示退出，避免等待源码编译。
export RELAY_KERNEL_MODE=prebuilt
# 默认 auto；排查时可以改为 source，强制源码编译。
# export RELAY_KERNEL_MODE=source
```

`RELAY_KERNEL_REPO` 可指定预编译包来源，默认与 `RELAY_REPO` 相同。请仅使用可信仓库。源码编译回退会校验 Go 压缩包 SHA256，并优先复用版本、架构匹配的 Go 工具链。
