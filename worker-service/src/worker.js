import {isIP} from 'node:net';
const encoder=new TextEncoder();
const now=()=>Math.floor(Date.now()/1000);
const random=()=>Array.from(crypto.getRandomValues(new Uint8Array(32)),n=>n.toString(16).padStart(2,'0')).join('');
export async function digest(text){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',encoder.encode(text))),b=>b.toString(16).padStart(2,'0')).join('')}
export function equal(a,b){if(typeof a!=='string'||typeof b!=='string')return false;let diff=a.length^b.length;for(let i=0;i<Math.max(a.length,b.length);i++)diff|=(a.charCodeAt(i)||0)^(b.charCodeAt(i)||0);return diff===0}
export async function passwordHash(password,salt){const key=await crypto.subtle.importKey('raw',encoder.encode(password),'PBKDF2',false,['deriveBits']);return Array.from(new Uint8Array(await crypto.subtle.deriveBits({name:'PBKDF2',hash:'SHA-256',salt:encoder.encode(salt),iterations:100000},key,256)),b=>b.toString(16).padStart(2,'0')).join('')}
const security={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"};
function response(value,status=200,headers={}){return new Response(typeof value==='string'?value:JSON.stringify(value),{status,headers:{...security,'Content-Type':'application/json; charset=utf-8',...headers}})}
function fail(message,status=400,code){throw Object.assign(Error(message),{status,code})}
function validPassword(value){if(typeof value!=='string'||value.length<12||value.length>256)fail('密码长度必须为 12–256 个字符')}
export function publicIP(ip){if(isIP(ip)===4){const [a,b]=ip.split('.').map(Number);return !(a===0||a===10||a===127||a>=224||a===169&&b===254||a===172&&b>=16&&b<=31||a===192&&b===168||a===100&&b>=64&&b<=127||a===198&&(b===18||b===19))}if(isIP(ip)===6){const n=ip.toLowerCase();return /^[23][0-9a-f]{0,3}:/.test(n)&&!(/^f[cdfe]/.test(n)||n==='::'||n==='::1'||n.includes('.')||n.startsWith('::ffff:'))}return false}
export function originURL(value){let url;try{url=new URL(value)}catch{fail('回源地址无效')}
 if(url.protocol!=='https:'||(url.port&&!['443','8443'].includes(url.port))||url.username||url.password||url.search||url.hash||url.pathname.includes('%')||!/^\/(?:[A-Za-z0-9_-]+\/)*sub\/?$/.test(url.pathname))fail('回源需为 HTTPS 订阅接口，不带查询参数')
 if(isIP(url.hostname.replace(/^\[|\]$/g,''))||!/^([a-z0-9][a-z0-9-]*\.)+[a-z]{2,63}$/.test(url.hostname)||/\.(localhost|local|internal|test|invalid)$/.test(url.hostname))fail('回源需使用公网域名及受信任的 HTTPS 证书')
 return url.href.replace(/\/$/,'')}
async function ensurePublicDNS(origin,fetcher){const host=new URL(origin).hostname;let addresses=[];
 for(const type of ['A','AAAA']){let r;try{r=await fetcher('https://cloudflare-dns.com/dns-query?name='+encodeURIComponent(host)+'&type='+type,{headers:{Accept:'application/dns-json'},signal:AbortSignal.timeout(6000)})}catch{fail('无法验证回源 DNS',502)}if(!r.ok)fail('无法验证回源 DNS',502);const data=await r.json();addresses.push(...(data.Answer||[]).filter(a=>a.type===1||a.type===28).map(a=>a.data))}
 if(!addresses.length||addresses.some(ip=>!publicIP(ip)))fail('回源域名必须仅解析到公网 IP');}
async function bodyJSON(request){if(!request.headers.get('Content-Type')?.startsWith('application/json'))fail('需要 JSON 请求',415);const reader=request.body?.getReader();if(!reader)fail('请求体无效');let size=0,parts=[];for(;;){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>16384){await reader.cancel();fail('请求过大',413)}parts.push(value)}const bytes=new Uint8Array(size);let offset=0;for(const p of parts){bytes.set(p,offset);offset+=p.length}try{const value=JSON.parse(new TextDecoder().decode(bytes));if(!value||Array.isArray(value)||typeof value!=='object')fail('请求体无效');return value}catch{fail('JSON 无效')}}
async function rate(db,request,group,limit){const ip=request.headers.get('CF-Connecting-IP')||'local';const key=group+':'+await digest(ip),bucket=Math.floor(now()/300);const row=await db.prepare('INSERT INTO attempts(key,bucket,count) VALUES(?,?,1) ON CONFLICT(key,bucket) DO UPDATE SET count=count+1 RETURNING count').bind(key,bucket).first();if(row.count>limit)fail('尝试次数过多，请稍后重试',429)}
async function session(db,request){const cookie=request.headers.get('Cookie')||'',token=/(?:^|;\s*)__Host-relay_admin=([a-f0-9]{64})(?:;|$)/.exec(cookie)?.[1];if(!token)return null;return db.prepare('SELECT s.token_hash,s.csrf,s.version,s.expires FROM sessions s JOIN admin a ON a.id=1 AND a.version=s.version WHERE s.token_hash=? AND s.expires>?').bind(await digest(token),now()).first()}
async function adminState(db,s){const settings=await db.prepare('SELECT * FROM settings WHERE id=1').first();const rows=await db.prepare('SELECT id,ip,name,origin,enabled,registered,last_seen,last_request FROM nodes ORDER BY registered DESC').all();return {csrf:s.csrf,username:'dywsun',registration:!!settings.registration,tokenConfigured:!!settings.token_hash,tokenUpdated:settings.token_updated,nodes:rows.results.map(n=>({...n,enabled:!!n.enabled}))}}
const cookie=(value,maxAge=28800)=>`__Host-relay_admin=${value}; Secure; HttpOnly; SameSite=Strict; Path=/; Max-Age=${maxAge}`;
export function makeWorker(fetcher=(...args)=>fetch(...args)){
return {async fetch(request,env,ctx){try{
 const url=new URL(request.url),path=url.pathname,db=env.DB.withSession?env.DB.withSession('first-primary'):env.DB;
 if(url.protocol!=='https:'&&url.hostname!=='localhost'&&url.hostname!=='127.0.0.1')return response({error:'需要 HTTPS'},403);
 // Explicit whitelist: source files, databases and configuration are never web assets.
 if(request.method==='GET'&&['/','/assets/app.js','/assets/style.css'].includes(path)){
   const assets=typeof RELAY_ASSETS==='undefined'?{}:RELAY_ASSETS;
   if(!(path in assets))return response({error:'请先构建 Worker'},503);
   return response(assets[path],200,{'Content-Type':path==='/'?'text/html; charset=utf-8':path.endsWith('.js')?'text/javascript; charset=utf-8':'text/css; charset=utf-8'});
 }
 if(path==='/api/bootstrap'&&request.method==='GET'){const a=await db.prepare('SELECT id FROM admin WHERE id=1').first();return response({initialized:!!a,username:'dywsun'})}
 if(path.startsWith('/sub/')&&['GET','HEAD'].includes(request.method)){
   const m=/^\/sub\/([a-f0-9-]{36})\/([A-Za-z0-9_-]{32,128})$/.exec(path);if(!m)return response('Not found',404,{'Content-Type':'text/plain'});
   const node=await db.prepare('SELECT * FROM nodes WHERE id=? AND enabled=1').bind(m[1]).first();if(!node)return response('Not found',404,{'Content-Type':'text/plain'});
   const fmt=url.searchParams.get('format')||'uri';if(!['uri','karing','mihomo','singbox'].includes(fmt))fail('格式无效');
   const origin=originURL(node.origin);if(new URL(origin).hostname===url.hostname)fail('回源不能指向自身');await ensurePublicDNS(origin,fetcher);
   let upstream;try{upstream=await fetcher(origin+'/'+m[2]+'?format='+fmt,{method:request.method,redirect:'manual',cache:'no-store',signal:AbortSignal.timeout(10000),headers:{'Accept-Encoding':'identity'}})}catch{return response('Subscription origin unavailable',502,{'Content-Type':'text/plain'})}
   if(upstream.status>=300&&upstream.status<400){await upstream.body?.cancel();return response('Origin redirects are not allowed',502,{'Content-Type':'text/plain'})}
   // Recheck after network I/O so a concurrent disable/delete cannot release a new subscription.
   const active=await db.prepare('SELECT id FROM nodes WHERE id=? AND enabled=1 AND origin=?').bind(node.id,node.origin).first();if(!active){await upstream.body?.cancel();return response('Not found',404,{'Content-Type':'text/plain'})}
   const update=db.prepare('UPDATE nodes SET last_request=? WHERE id=?').bind(now(),node.id).run();if(ctx)ctx.waitUntil(update);else await update;
   const type=upstream.headers.get('Content-Type')||'text/plain; charset=utf-8';
   const headers={...security,'Content-Security-Policy':"default-src 'none'; sandbox",'Content-Type':/^(text\/(plain|yaml)|application\/(json|yaml|octet-stream))(;|$)/i.test(type)?type:'text/plain; charset=utf-8'};
   for(const name of ['Subscription-Userinfo','profile-update-interval'])if(upstream.headers.has(name))headers[name]=upstream.headers.get(name);
   return new Response(upstream.body,{status:upstream.status,headers});
 }
 if(path==='/api/register'&&request.method==='POST'){
   await rate(db,request,'register',20);const p=await bodyJSON(request),settings=await db.prepare('SELECT * FROM settings WHERE id=1').first();
   const token=request.headers.get('Authorization')?.replace(/^Bearer /,'')||'';
   if(!settings.registration)fail('Registration is paused',403,'REGISTRATION_PAUSED');
   if(!settings.token_hash)fail('Registration token has not been saved',403,'TOKEN_NOT_CONFIGURED');
   if(!equal(await digest(token),settings.token_hash))fail('Registration token does not match',403,'TOKEN_MISMATCH');
   if(!/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(p.id)||!publicIP(p.ip)||typeof p.name!=='string'||!p.name.trim()||p.name.length>64||! /^[a-f0-9]{64}$/.test(p.key))fail('UUID、公网 IP、名称或管理密钥无效');
   const origin=originURL(p.origin);if(new URL(origin).hostname===url.hostname)fail('回源不能指向 Worker 自身');await ensurePublicDNS(origin,fetcher);
   const hash=await digest(p.key),old=await db.prepare('SELECT * FROM nodes WHERE id=?').bind(p.id).first();
   if(old){if(!equal(old.key_hash,hash)||old.ip!==p.ip||old.origin!==origin)fail('UUID 已绑定其他机器，请用独立管理密钥更新',409);return response({ok:true,id:p.id})}
   const result=await db.prepare('INSERT OR IGNORE INTO nodes(id,ip,name,origin,key_hash,registered,last_seen) VALUES(?,?,?,?,?,?,?)').bind(p.id,p.ip,p.name.trim(),origin,hash,now(),now()).run();if(!result.meta.changes)fail('UUID 已注册，请重试',409);
   return response({ok:true,id:p.id});
 }
 if(path==='/api/node/update'&&request.method==='POST'){
   const p=await bodyJSON(request),node=await db.prepare('SELECT * FROM nodes WHERE id=?').bind(p.id||'').first();const token=request.headers.get('Authorization')?.replace(/^Bearer /,'')||'';
   if(!node||!equal(node.key_hash,await digest(token)))fail('VPS 管理密钥无效',403);
   if(p.ip&&!publicIP(p.ip))fail('公网 IP 无效');const origin=p.origin?originURL(p.origin):node.origin;
   if(new URL(origin).hostname===url.hostname)fail('回源不能指向自身');if(p.origin)await ensurePublicDNS(origin,fetcher);
   const update=await db.prepare('UPDATE nodes SET ip=?,origin=?,last_seen=? WHERE id=? AND key_hash=?').bind(p.ip||node.ip,origin,now(),node.id,node.key_hash).run();if(!update.meta.changes)fail('绑定已撤销',403);return response({ok:true,enabled:!!node.enabled});
 }
 if(path==='/api/state'&&request.method==='GET'){const s=await session(db,request);if(!s)fail('请先登录',401);return response(await adminState(db,s))}
 if(request.method!=='POST')return response({error:'Not found'},404);
 if(request.headers.get('Origin')!==url.origin)fail('请求来源无效',403);
 const p=await bodyJSON(request);
 if(path==='/api/setup'){
   await rate(db,request,'setup',10);if(await db.prepare('SELECT id FROM admin WHERE id=1').first())fail('管理员已初始化',409);
   validPassword(p.password);if(p.password!==p.confirm)fail('两次密码不一致');const salt=random(),hash=await passwordHash(p.password,salt);
   const result=await db.prepare('INSERT OR IGNORE INTO admin(id,salt,hash) VALUES(1,?,?)').bind(salt,hash).run();if(!result.meta.changes)fail('管理员已初始化',409);return response({ok:true});
 }
 if(path==='/api/login'){
   await rate(db,request,'login',15);const a=await db.prepare('SELECT * FROM admin WHERE id=1').first();if(!a)fail('请先设置密码',409);
   const hash=await passwordHash(typeof p.password==='string'?p.password.slice(0,257):'',a.salt);if(p.username!=='dywsun'||!equal(a.hash,hash))fail('账号或密码错误',401);
   const token=random(),csrf=random();await db.prepare('INSERT INTO sessions(token_hash,csrf,version,expires) SELECT ?,?,version,? FROM admin WHERE id=1 AND version=?').bind(await digest(token),csrf,now()+28800,a.version).run();
   return response({csrf},200,{'Set-Cookie':cookie(token)});
 }
 const s=await session(db,request);if(!s)fail('请先登录',401);if(!equal(request.headers.get('X-CSRF-Token'),s.csrf))fail('CSRF 校验失败',403);
 if(path==='/api/logout'){await db.prepare('DELETE FROM sessions WHERE token_hash=?').bind(s.token_hash).run();return response({ok:true},200,{'Set-Cookie':cookie('',0)})}
 if(path==='/api/password'){
   await rate(db,request,'password',10);const a=await db.prepare('SELECT * FROM admin WHERE id=1').first();if(typeof p.current!=='string'||p.current.length>256||!equal(await passwordHash(p.current,a.salt),a.hash))fail('原密码错误',403);
   validPassword(p.password);if(p.password!==p.confirm)fail('两次新密码不一致');const salt=random(),hash=await passwordHash(p.password,salt);
   const result=await db.prepare('UPDATE admin SET salt=?,hash=?,version=version+1 WHERE id=1 AND version=?').bind(salt,hash,a.version).run();if(!result.meta.changes)fail('密码已更新，请重新登录',409);
   await db.prepare('DELETE FROM sessions WHERE version<=?').bind(a.version).run();return response({ok:true},200,{'Set-Cookie':cookie('',0)});
 }
 if(path==='/api/settings'){
   if(typeof p.registration!=='boolean')fail('注册设置无效');let hash=null;
   if(typeof p.token==='string')p.token=p.token.trim();
   if(p.token!==undefined){if(typeof p.token!=='string'||p.token.length<24||p.token.length>256)fail('注册令牌长度必须为 24–256 位');hash=await digest(p.token)}
   if(hash)await db.prepare('UPDATE settings SET registration=?,token_hash=?,token_updated=? WHERE id=1').bind(+p.registration,hash,now()).run();else await db.prepare('UPDATE settings SET registration=? WHERE id=1').bind(+p.registration).run();
   return response(await adminState(db,s));
 }
 if(path==='/api/node/action'){
   if(!['enable','disable','delete'].includes(p.action))fail('操作无效');
   if(p.action==='delete')await db.prepare('DELETE FROM nodes WHERE id=?').bind(p.id).run();else await db.prepare('UPDATE nodes SET enabled=? WHERE id=?').bind(p.action==='enable'?1:0,p.id).run();
   return response(await adminState(db,s));
 }
 return response({error:'Not found'},404);
}catch(e){return response({code:e.code,error:e.status?e.message:'服务暂不可用，请检查数据库绑定与表结构'},e.status||503)}}};}
export default makeWorker();
