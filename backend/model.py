"""Validated domain model and sing-box config/subscription generation."""
import base64
import copy
import datetime as dt
import json
import re
import secrets
import uuid
from urllib.parse import quote, urlencode

KINDS = {'VMess': 'vmess', 'TUIC v5': 'tuic', 'VLESS': 'vless', 'Hysteria2': 'hysteria2', 'AnyTLS': 'anytls'}
PORTS = {'VMess': 8880, 'TUIC v5': 32786, 'VLESS': 10443, 'Hysteria2': 10444, 'AnyTLS': 10446}

def credential(name):
    result = {}
    if name in ('VMess', 'TUIC v5', 'VLESS'):
        result['uuid'] = str(uuid.uuid4())
    if name in ('TUIC v5', 'Hysteria2', 'AnyTLS'):
        result['password'] = secrets.token_urlsafe(24)
    return result

def initial(ports=None):
    return {'revision': 0, 'users': [], 'protocols': [
        {'name': n, 'port': (ports or PORTS)[n], 'active': n in ('VMess', 'TUIC v5')}
        for n in KINDS], 'rules': [True, True, True, True], 'fallback': '节点选择'}

def validate(s, reserved=()):
    assert isinstance(s, dict) and isinstance(s.get('users'), list), '用户列表无效'
    assert len(s['users']) <= 2000, '最多支持 2000 位用户'
    assert len(s.get('protocols', [])) <= 5, '协议列表无效'
    names, ports = set(), set(reserved)
    for p in s['protocols']:
        assert p['name'] in KINDS and p['name'] not in names, '每种协议只能配置一个入口'
        assert type(p['port']) is int and 1024 <= p['port'] <= 65535, '协议端口范围为 1024–65535'
        assert p['port'] not in ports, '端口冲突'
        assert type(p['active']) is bool, '协议状态无效'
        names.add(p['name']); ports.add(p['port'])
    ids, tokens, credentials = set(), set(), set()
    for u in s['users']:
        assert re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', u['id']), '用户 ID 无效'
        assert u['id'] not in ids, '用户 ID 重复'
        ids.add(u['id'])
        assert isinstance(u['name'], str) and 1 <= len(u['name'].strip()) <= 40, '用户名长度为 1–40'
        assert type(u['active']) is bool, '用户状态无效'
        assert re.fullmatch(r'[A-Za-z0-9_-]{32,128}', u['token']), '订阅令牌无效'
        assert u['token'] not in tokens, '订阅令牌重复'
        tokens.add(u['token'])
        dt.date.fromisoformat(u['expire'])
        assert type(u['quota']) in (int, float) and 0 < u['quota'] <= 100000, '额度无效'
        assert isinstance(u['credentials'], dict), '凭据无效'
        for n, c in u['credentials'].items():
            assert n in names, '用户引用不存在的协议'
            expected = credential(n)
            assert set(c) == set(expected), '凭据字段不完整'
            for k, v in c.items():
                assert isinstance(v, str), '凭据无效'
                if k == 'uuid': uuid.UUID(v)
                else: assert re.fullmatch(r'[A-Za-z0-9_-]{16,128}', v), '密码格式无效'
                assert (n, k, v) not in credentials, '用户凭据重复'
                credentials.add((n, k, v))
    assert len(s['rules']) == 4 and all(type(x) is bool for x in s['rules']), '规则设置无效'
    assert s['fallback'] in ('节点选择', '自动选择', '直连'), '默认策略无效'
    return s

def eligible(u, usage=None):
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()
    return u['active'] and dt.date.fromisoformat(u['expire']) >= now and (usage or {}).get(u['id'], 0) < u['quota'] * 1024**3

def counter_name(u, protocol):
    return u['id'] + ':' + KINDS[protocol]

def server_config(s, settings, usage=None):
    validate(s, (settings['web_port'], settings['api_port'], settings['stats_port']))
    tls = {'enabled': True, 'certificate_path': settings['cert'], 'key_path': settings['key']}
    inbounds, names = [], []
    for p in s['protocols']:
        if not p['active']: continue
        n, kind = p['name'], KINDS[p['name']]
        rows = []
        for u in s['users']:
            if n not in u['credentials'] or not eligible(u, usage): continue
            user = {'name': counter_name(u, n), **u['credentials'][n]}
            if kind == 'vless': user['flow'] = 'xtls-rprx-vision'
            if kind == 'vmess': user['alterId'] = 0
            rows.append(user); names.append(user['name'])
        # Do not expose unauthenticated/empty protocol listeners.
        if not rows: continue
        inbound = {'type': kind, 'tag': kind, 'listen': '::', 'listen_port': p['port'], 'users': rows}
        if kind == 'vless':
            inbound['tls'] = {'enabled': True, 'server_name': settings['reality_sni'], 'reality': {'enabled': True, 'handshake': {'server': settings.get('reality_handshake_host',settings['reality_sni']), 'server_port': settings.get('reality_handshake_port',443)}, 'private_key': settings['reality_private'], 'short_id': [settings['short_id']]}}
        else:
            inbound['tls'] = copy.deepcopy(tls)
            if kind == 'vmess':
                inbound['transport'] = {'type': 'ws', 'path': settings.get('vmess_ws_path','/relay-vmess'), 'max_early_data':2048, 'early_data_header_name':'Sec-WebSocket-Protocol'}
                if not settings.get('vmess_tls',False): inbound.pop('tls')
            if kind == 'tuic':
                inbound['congestion_control'] = settings.get('tuic_congestion_control','bbr'); inbound['tls']['alpn'] = ['h3']
            if kind == 'hysteria2':
                inbound['tls']['alpn'] = ['h3']; inbound['ignore_client_bandwidth'] = False
        inbounds.append(inbound)
    return {'log': {'level': 'warn', 'timestamp': True}, 'inbounds': inbounds, 'outbounds': [{'type': 'direct', 'tag': 'direct'}], 'experimental': {'v2ray_api': {'listen': '127.0.0.1:' + str(settings['stats_port']), 'stats': {'enabled': True, 'users': names, 'inbounds': [p['tag'] for p in inbounds]}}}}

def client_nodes(s, u, settings, usage=None):
    if not eligible(u, usage): return []
    result = []
    for p in s['protocols']:
        n, kind = p['name'], KINDS[p['name']]
        if not p['active'] or n not in u['credentials']: continue
        node = {'type': kind, 'tag': n, 'server': settings['host'], 'server_port': p['port'], **u['credentials'][n]}
        node['tls'] = {'enabled': True, 'server_name': settings['tls_name'], 'insecure': settings.get('self_signed', False)}
        if kind == 'vless':
            node['flow'] = 'xtls-rprx-vision'; node['tls'] = {'enabled': True, 'server_name': settings['reality_sni'], 'utls': {'enabled': True, 'fingerprint': 'chrome'}, 'reality': {'enabled': True, 'public_key': settings['reality_public'], 'short_id': settings['short_id']}}
        if kind == 'vmess':
            node['security'] = 'auto'; node['alter_id'] = 0; node['transport'] = {'type': 'ws', 'path': settings.get('vmess_ws_path','/relay-vmess'), 'max_early_data':2048, 'early_data_header_name':'Sec-WebSocket-Protocol'}
            if not settings.get('vmess_tls',False): node['tls'] = {'enabled':False,'server_name':settings['tls_name']}
        if kind == 'tuic': node['congestion_control'] = settings.get('tuic_congestion_control','bbr'); node['tls']['alpn'] = ['h3']
        if kind == 'hysteria2': node['tls']['alpn'] = ['h3']
        result.append(node)
    return result

def subscription(s, u, settings, fmt, usage=None):
    nodes = client_nodes(s, u, settings, usage)
    if fmt in ('uri', 'karing'):
        links = []
        host = settings['host']; host = '[' + host + ']' if ':' in host else host
        for n in nodes:
            kind, tag = n['type'], n['tag']
            if kind == 'vmess':
                obj = {'v': '2', 'ps': tag, 'add': settings['host'], 'port': str(n['server_port']), 'id': n['uuid'], 'aid': '0', 'scy': 'auto', 'net': 'ws', 'type': 'none', 'host': settings['tls_name'], 'path': settings.get('vmess_ws_path','/relay-vmess'), 'tls': 'tls' if settings.get('vmess_tls',False) else '', 'sni': settings['tls_name'], 'allowInsecure': '1' if settings.get('self_signed') else '0'}
                links.append('vmess://' + base64.b64encode(json.dumps(obj).encode()).decode()); continue
            query = {'sni': n['tls']['server_name']}
            if settings.get('self_signed') and kind != 'vless': query['insecure'] = '1'; query['allowInsecure'] = '1'
            if kind == 'vless': query.update({'security': 'reality', 'flow': n['flow'], 'fp': 'chrome', 'pbk': settings['reality_public'], 'sid': settings['short_id'], 'type': 'tcp', 'encryption': 'none'})
            if kind in ('tuic', 'hysteria2'): query['alpn'] = 'h3'
            if kind == 'tuic': query['congestion_control'] = settings.get('tuic_congestion_control','bbr')
            auth = n.get('uuid', n.get('password', ''))
            if kind == 'tuic': auth += ':' + n['password']
            links.append(f'{kind}://{quote(auth, safe=":")}@{host}:{n["server_port"]}?{urlencode(query)}#{quote(tag)}')
        return base64.b64encode('\n'.join(links).encode()), 'text/plain; charset=utf-8'
    if fmt == 'mihomo':
        proxies = []
        for n in nodes:
            p = {'name': n['tag'], 'type': n['type'], 'server': n['server'], 'port': n['server_port'], 'udp': True}
            for k in ('uuid', 'password'): 
                if k in n: p[k] = n[k]
            t = n['tls']; p.update({'sni': t['server_name'], 'skip-cert-verify': t.get('insecure', False)})
            if n['type'] == 'vmess': p.update({'alterId': 0, 'cipher': 'auto', 'tls': settings.get('vmess_tls',False), 'servername': t['server_name'], 'network': 'ws', 'ws-opts': {'path': settings.get('vmess_ws_path','/relay-vmess'), 'headers': {'Host': t['server_name']}, 'max-early-data':2048, 'early-data-header-name':'Sec-WebSocket-Protocol'}})
            if n['type'] == 'vless': p.update({'tls': True, 'flow': n['flow'], 'client-fingerprint': 'chrome', 'reality-opts': {'public-key': settings['reality_public'], 'short-id': settings['short_id']}})
            if n['type'] == 'tuic': p.update({'alpn': ['h3'], 'congestion-controller': settings.get('tuic_congestion_control','bbr')})
            if n['type'] == 'hysteria2': p['alpn'] = ['h3']
            proxies.append(p)
        rules = []
        if s['rules'][0]: rules += ['IP-CIDR,10.0.0.0/8,DIRECT,no-resolve', 'IP-CIDR,172.16.0.0/12,DIRECT,no-resolve', 'IP-CIDR,192.168.0.0/16,DIRECT,no-resolve', 'IP-CIDR,127.0.0.0/8,DIRECT,no-resolve', 'IP-CIDR6,fc00::/7,DIRECT,no-resolve', 'IP-CIDR6,::1/128,DIRECT,no-resolve', 'IP-CIDR6,fe80::/10,DIRECT,no-resolve']
        if s['rules'][1]: rules += ['GEOSITE,cn,DIRECT']
        if s['rules'][2]: rules += ['GEOIP,CN,DIRECT']
        fallback = 'DIRECT' if s['fallback'] == '直连' else s['fallback']
        rules += ['MATCH,' + fallback]
        obj = {'mixed-port': 7890, 'allow-lan': False, 'mode': 'rule', 'proxies': proxies, 'proxy-groups': [{'name': '节点选择', 'type': 'select', 'proxies': ['自动选择'] + [n['name'] for n in proxies]}, {'name': '自动选择', 'type': 'url-test', 'proxies': [n['name'] for n in proxies] or ['DIRECT'], 'url': 'https://www.gstatic.com/generate_204', 'interval': 300}], 'rules': rules}
        # JSON is valid YAML 1.2 and supported by Mihomo's YAML parser.
        return json.dumps(obj, ensure_ascii=False, indent=2).encode(), 'application/yaml; charset=utf-8'
    if fmt == 'singbox':
        tags = [n['tag'] for n in nodes]
        route_rules = []
        if s['rules'][0]: route_rules.append({'ip_is_private': True, 'outbound': 'direct'})
        sets = []
        for enabled, tag, url in [(s['rules'][1], 'cn-domain', 'https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-cn.srs'), (s['rules'][2], 'cn-ip', 'https://raw.githubusercontent.com/SagerNet/sing-geoip/rule-set/geoip-cn.srs')]:
            if enabled:
                sets.append({'type': 'remote', 'tag': tag, 'format': 'binary', 'url': url, 'download_detour': '节点选择', 'update_interval': '1d' if s['rules'][3] else '87600h'})
                route_rules.append({'rule_set': tag, 'outbound': 'direct'})
        obj = {'inbounds': [{'type': 'mixed', 'tag': 'mixed-in', 'listen': '127.0.0.1', 'listen_port': 7890}], 'outbounds': [{'type': 'selector', 'tag': '节点选择', 'outbounds': ['自动选择'] + tags}, {'type': 'urltest', 'tag': '自动选择', 'outbounds': tags or ['direct'], 'url': 'https://www.gstatic.com/generate_204', 'interval': '5m'}] + nodes + [{'type': 'direct', 'tag': 'direct'}], 'route': {'rules': route_rules, 'rule_set': sets, 'final': 'direct' if s['fallback'] == '直连' else s['fallback']}}
        return json.dumps(obj, ensure_ascii=False, indent=2).encode(), 'application/json'
    raise ValueError('不支持的订阅格式')
