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

默认固定 sing-box **1.14.4**。先校验官方发布包 SHA256。官方默认构建不含 `with_v2ray_api` 时，安装器自动下载并校验 Go 1.26.10 工具链，从对应版本官方源码编译 `with_quic,with_utls,with_v2ray_api` 内核。首次编译可能需要数分钟、网络访问与较多内存；本项目没有把未验证的空统计伪装成正常数据。

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
- 订阅：Karing/URI 返回 Base64 分享链接集合；Mihomo 返回 YAML 1.2 兼容的 JSON 完整配置（JSON 是 YAML 1.2 子集）；sing-box 返回 JSON。完整配置包含选择/测速组、国内分流规则。Karing 节点订阅使用其自身分流设置。
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

使用 sing-box V2Ray gRPC StatsService，`users[].name` 采用 `用户ID:协议`。VMess/TUIC 将认证后的用户名称传入连接元数据，采集该用户的 TCP/UDP 上下行计数。后台每 10 秒读取不重置的远端计数，SQLite 保存增量，并按 systemd 进程启动单调时间戳 区分内核重启。原始用户计数按协议存储，页面展示用户本月合计及小时曲线。

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
bash -n install.sh scripts/build-sing-box.sh
```

可选真实内核测试：设置 `SING_BOX_BIN=/absolute/path/to/sing-box` 后执行 `python3 scripts/check_configs.py`。该脚本需要本地 openssl，校验全部服务端入口及 sing-box 客户端配置，不修改系统配置。

## 来源

安装流程参考 [sing-box-yg](https://github.com/yonggekkk/sing-box-yg)，本仓库未复制执行其完整脚本。内核、统计接口与协议配置依据 [sing-box 官方文档](https://sing-box.sagernet.org/) 和对应固定版本源码。第三方内核及依赖保留各自许可证。

## 已执行验证与边界

本地已使用官方 1.14.4 源码构建统计内核，完成 VMess/TUIC 双用户的 TCP + UDP 回环实测和四组用户/协议独立上下行计数验证。`scripts/smoke_protocols.py` 可复现（需 requirements 与 SING_BOX_BIN）。五种协议服务端与 sing-box 客户端配置均经真实内核 check。Ubuntu/CentOS 的包管理、Nginx/SELinux/systemd 整机部署仍需在对应干净 VPS 验收；macOS 本机测试不能替代该步骤。

网站自动证书机制依据 [acme.sh 文档](https://github.com/acmesh-official/acme.sh) 和 [Let’s Encrypt HTTP-01 说明](https://letsencrypt.org/docs/challenge-types/)。Cloudflare 代理端口见 [官方端口列表](https://developers.cloudflare.com/fundamentals/reference/network-ports/)。
