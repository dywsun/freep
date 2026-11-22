# Relay Worker 订阅网关

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
