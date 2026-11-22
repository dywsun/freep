"""Independent VPS registration; Worker proxies subscriptions without storing user data."""
import ipaddress
import json
import re
import secrets
import socket
import threading
import time
import uuid
from urllib.parse import urlsplit
from urllib.request import Request, HTTPSHandler, HTTPRedirectHandler, build_opener
from urllib.error import HTTPError

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

def request(url,method='GET',body=None,headers=None):
    if not url.startswith('https://'):raise ValueError('仅允许 HTTPS')
    try:
        with build_opener(HTTPSHandler(),NoRedirect()).open(Request(url,data=body,method=method,headers={'User-Agent':'Relay-VPS/1.0','Accept':'application/json',**(headers or {})}),timeout=25) as response:
            raw=response.read(2_000_001)
            if len(raw)>2_000_000:raise ValueError('响应过大')
            return json.loads(raw) if raw else {}
    except HTTPError as e:
        codes={'REGISTRATION_PAUSED':'Worker 已暂停新 VPS 注册，请在 Worker 面板开启「允许新 VPS 注册」。',
               'TOKEN_NOT_CONFIGURED':'Worker 尚未保存注册令牌。随机生成后还需要点击「保存注册令牌」。',
               'TOKEN_MISMATCH':'注册令牌与 Worker 保存的不一致。请使用最近一次保存的注册令牌，不是管理员登录密码或 VPS 独立密钥。'}
        raw=e.read(4096)
        if e.code==403 and re.search(rb'error\s+code\s*:\s*1010',raw,re.I):
            raise ValueError('Cloudflare 1010: Browser Integrity Check blocked this request before Worker authentication. Update the VPS client User-Agent; this is not a registration-token error.') from None
        try:
            detail=json.loads(raw)
        except (ValueError,OSError):detail={}
        if isinstance(detail,dict) and detail.get('code') in codes:
            raise ValueError(codes[detail['code']]) from None
        if e.code==403 and 'json' not in e.headers.get('Content-Type','').lower():
            raise ValueError('Worker 返回了非 JSON 的 HTTP 403，可能被 Cloudflare WAF、Access 或浏览器验证拦截；请检查该域名的安全规则。') from None
        messages={403:'注册令牌或独立管理密钥无效，或注册已暂停',409:'UUID 已绑定，请勿覆盖其他 VPS',429:'尝试次数过多，请稍后重试'}
        raise ValueError(messages.get(e.code,'Worker 请求失败（HTTP %s），请检查服务部署、域名与公网回源地址'%e.code)) from None
    except (OSError,TimeoutError):raise ValueError('Worker 连接失败，请检查域名和网络') from None

def public_ip(value):
    try:
        ip=ipaddress.ip_address(value)
        if not ip.is_global:raise ValueError()
        return str(ip)
    except ValueError:raise ValueError('需要有效的 VPS 公网 IP') from None

def https_url(value,base_only=False):
    try:
        u=urlsplit(str(value).strip())
        if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment or u.port not in ((None,443) if base_only else (None,443,8443)):raise ValueError()
        if not re.fullmatch(r'(?:[a-zA-Z0-9][a-zA-Z0-9-]*\.)+[a-zA-Z]{2,63}',u.hostname):raise ValueError()
        if base_only and u.path not in ('','/'):raise ValueError()
        if not base_only and not re.fullmatch(r'/(?:[A-Za-z0-9_-]+/)*sub/?',u.path):raise ValueError()
        return ('https://'+u.hostname+(':8443' if u.port==8443 else '')+('' if base_only else u.path)).rstrip('/')
    except ValueError:raise ValueError('请填写公网 HTTPS 域名，使用Worker 443 / 回源 443 或 8443 端口；Worker 地址不带路径，回源地址以 /sub 结尾') from None

class Cloudflare:
    def __init__(self,store):
        self.store=store;self.lock=threading.RLock();self.path=store.directory/'gateway.json'
        self.config=json.loads(self.path.read_text()) if self.path.exists() else {'id':str(uuid.uuid4()),'key':secrets.token_hex(32),'mode':'local','registered':False}
        if not self.path.exists():self.save()
        self.status='已注册，尚未检查连接' if self.config.get('registered') else '尚未注册';self.last_sync=None;self.thread=None
    def save(self):
        from app import atomic
        atomic(self.path,self.config)
    def public(self):
        return {k:self.config.get(k,'') for k in ('id','url','ip','origin','name','mode')}|{'configured':bool(self.config.get('registered')),'status':self.status,'last_sync':self.last_sync}
    def subscription_base(self):
        if self.config.get('mode')=='worker' and self.config.get('registered'):
            return self.config['url']+'/sub/'+self.config['id']
        return self.store.settings['public_url'].rstrip('/')+'/sub'
    def start(self):
        if self.thread or not self.config.get('registered'):return
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def run(self):
        while True:
            time.sleep(60)
            try:self.sync()
            except Exception as e:self.status='绑定检查失败：'+str(e)
    def changed(self):pass  # User changes stay on this VPS; no subscription snapshots are uploaded.
    def register(self,p):
        if self.store.settings.get('preview'):raise ValueError('本地模拟 VPS 不允许向真实 Worker 注册')
        url=https_url(p.get('url',''),True);token=p.get('token','')
        if isinstance(token,str):token=token.strip()
        if not isinstance(token,str) or not 24<=len(token)<=256:raise ValueError('请输入 24–256 位注册令牌')
        host=urlsplit(self.store.settings['public_url']).hostname
        origin=https_url(p.get('origin') or ('https://'+host+':8443'+self.store.settings.get('base_path','')+'/sub'))
        ip=p.get('ip','').strip()
        if not ip:
            try:ip=request('https://api.ipify.org?format=json')['ip']
            except Exception:raise ValueError('自动获取公网 IP 失败，请手动填写') from None
        ip=public_ip(ip);name=str(p.get('name') or socket.gethostname()).strip()
        if not 1<=len(name)<=64:raise ValueError('VPS 名称长度为 1–64')
        with self.lock:
            payload={'id':self.config['id'],'key':self.config['key'],'ip':ip,'name':name,'origin':origin}
            result=request(url+'/api/register','POST',json.dumps(payload).encode(),{'Authorization':'Bearer '+token,'Content-Type':'application/json'})
            if not result.get('ok') or result.get('id')!=self.config['id']:raise ValueError('Worker 返回无效的注册结果')
            self.config.update({'url':url,'origin':origin,'ip':ip,'name':name,'registered':True})
            self.save();self.status='注册成功';self.last_sync=int(time.time());self.start()
        return self.public()
    def configure(self,p):
        mode=p.get('mode')
        if mode not in ('local','worker'):raise ValueError('订阅入口无效')
        with self.lock:
            if mode=='worker' and not self.config.get('registered'):raise ValueError('请先注册 Worker')
            self.config['mode']=mode;self.save()
        return self.public()
    def sync(self,p=None):
        with self.lock:
            if not self.config.get('registered'):raise ValueError('请先注册 Worker')
            payload={'id':self.config['id']}
            if p and p.get('ip'):payload['ip']=public_ip(p['ip'])
            if p and p.get('origin'):payload['origin']=https_url(p['origin'])
            result=request(self.config['url']+'/api/node/update','POST',json.dumps(payload).encode(),{'Authorization':'Bearer '+self.config['key'],'Content-Type':'application/json'})
            if not result.get('ok'):raise ValueError('Worker 返回无效结果')
            for k in ('ip','origin'):
                if k in payload:self.config[k]=payload[k]
            self.save();self.last_sync=int(time.time());self.status='连接正常' if result.get('enabled') else 'Worker 管理员已禁用本机订阅代理'
        return self.public()
