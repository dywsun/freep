#!/usr/bin/env python3
"""Optional local-only VMess/TUIC TCP+UDP and per-user stats integration test."""
import base64
import copy
import http.server
import json
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from model import initial, credential, server_config, client_nodes
from stats import query

binary=os.environ['SING_BOX_BIN']
def port(udp=False):
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM if udp else socket.SOCK_STREAM) as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]
def receive(sock,count):
    data=b''
    while len(data)<count:
        chunk=sock.recv(count-len(data))
        if not chunk:raise RuntimeError('Unexpected EOF')
        data+=chunk
    return data
def socks_connection(proxy,cmd,target):
    sock=socket.create_connection(('127.0.0.1',proxy),timeout=10);sock.sendall(b'\x05\x01\x00');assert receive(sock,2)==b'\x05\x00'
    sock.sendall(bytes([5,cmd,0,1])+socket.inet_aton('127.0.0.1')+struct.pack('!H',target))
    head=receive(sock,4);assert head[1]==0,head
    addr=receive(sock,4 if head[3]==1 else 16);bound=struct.unpack('!H',receive(sock,2))[0]
    return sock,socket.inet_ntop(socket.AF_INET if head[3]==1 else socket.AF_INET6,addr),bound
class HTTP(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body=b'relay-test-'*4096;self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def log_message(self,*_):pass

def main():
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp);processes=[]
        http_service=http.server.ThreadingHTTPServer(('127.0.0.1',0),HTTP);threading.Thread(target=http_service.serve_forever,daemon=True).start()
        udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);udp.bind(('127.0.0.1',0));udp.settimeout(1)
        stop=threading.Event()
        def echo():
            while not stop.is_set():
                try:data,addr=udp.recvfrom(8192);udp.sendto(data,addr)
                except socket.timeout:pass
                except OSError:return
        threading.Thread(target=echo,daemon=True).start()
        try:
            subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=localhost','-keyout',str(p/'key.pem'),'-out',str(p/'cert.pem')],check=True,capture_output=True)
            keys=dict(re.findall(r'(PrivateKey|PublicKey):\s*(\S+)',subprocess.check_output([binary,'generate','reality-keypair'],text=True)))
            stats_port=port();settings={'host':'127.0.0.1','tls_name':'localhost','self_signed':True,'web_port':18898,'api_port':18090,'stats_port':stats_port,'cert':str(p/'cert.pem'),'key':str(p/'key.pem'),'reality_private':keys['PrivateKey'],'reality_public':keys['PublicKey'],'reality_sni':'www.apple.com','short_id':'abcd','vmess_tls':False,'vmess_ws_path':'shared-entry-id-vm'}
            state=initial();state['protocols'][0]['port']=port();state['protocols'][1]['port']=port(True)
            state['users']=[{'id':name,'name':name,'token':name[0]*43,'active':True,'expire':'2099-12-31','quota':100,'credentials':{kind:credential(kind) for kind in ['VMess','TUIC v5']}} for name in ['alice','bob']]
            def launch(name,cfg):
                file=p/(name+'.json');file.write_text(json.dumps(cfg));log=open(p/(name+'.log'),'w');proc=subprocess.Popen([binary,'run','-c',str(file)],stdout=log,stderr=log);processes.append((proc,log));return proc
            server=launch('server',server_config(state,settings));time.sleep(1)
            for user in state['users']:
                for node in client_nodes(state,user,settings):
                    proxy=port();client=launch(user['id']+'-'+node['type'],{'log':{'level':'warn'},'inbounds':[{'type':'mixed','listen':'127.0.0.1','listen_port':proxy}],'outbounds':[node]});time.sleep(.5)
                    sock,_,_=socks_connection(proxy,1,http_service.server_port)
                    with sock:
                        sock.sendall(b'GET / HTTP/1.0\r\nHost: localhost\r\n\r\n');response=b''
                        while True:
                            chunk=sock.recv(65536)
                            if not chunk:break
                            response+=chunk
                        assert response.endswith(b'relay-test-'*4096)
                    control,address,udp_port=socks_connection(proxy,3,0)
                    with control,socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as packet:
                        packet.settimeout(10);payload=b'relay-udp-test';header=b'\x00\x00\x00\x01'+socket.inet_aton('127.0.0.1')+struct.pack('!H',udp.getsockname()[1]);packet.sendto(header+payload,('127.0.0.1',udp_port));reply,_=packet.recvfrom(8192);assert reply.endswith(payload),reply
                    print(user['id'],node['type'],'TCP + UDP passed',flush=True)
                    client.terminate();client.wait(timeout=10)
            values=query(stats_port)
            for user in state['users']:
                for kind in ['vmess','tuic']:
                    for direction in ['uplink','downlink']:
                        name=f'user>>>{user["id"]}:{kind}>>>traffic>>>{direction}';assert values.get(name,0)>0,(name,values)
            print('Both users and protocols have independent, positive uplink/downlink counters.')
        except Exception:
            for file in p.glob('*.log'):print(file.name,file.read_text(),file=sys.stderr)
            raise
        finally:
            stop.set();udp.close();http_service.shutdown();http_service.server_close()
            for proc,log in processes:
                if proc.poll() is None:proc.terminate();proc.wait(timeout=10)
                log.close()
if __name__=='__main__':main()
