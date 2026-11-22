"""Read-only system metrics. Rates use monotonic counter deltas, not proxy quotas."""
from collections import deque
import copy
from pathlib import Path
import platform
import threading
import time


def rate(current, previous, elapsed):
    return max(0, current-previous)/elapsed if elapsed and elapsed>0 else None


class SystemMonitor:
    def __init__(self, api=None, clock=time.monotonic):
        self.clock=clock;self.lock=threading.RLock();self.previous=None;self.history=deque(maxlen=60)
        self.latest={'available':False,'status':'资源采集尚未开始','sample_interval':5,'history':[]}
        if api is None:
            try: import psutil;api=psutil
            except ImportError: pass
        self.api=api
        if api: api.cpu_percent(interval=None)  # Prime the nonblocking CPU sampler.
    def sample(self):
        with self.lock:
            if not self.api:
                self.latest={'available':False,'status':'缺少 psutil 监控依赖','sample_interval':5,'history':[]};return
            try:
                p=self.api;now=self.clock();stamp=int(time.time());vm=p.virtual_memory();disk=p.disk_usage('/');io=p.disk_io_counters();net=p.net_io_counters(pernic=True);states=p.net_if_stats()
                elapsed=now-self.previous['clock'] if self.previous else None
                rows=[]
                for name,counter in net.items():
                    if name in ('lo','lo0'):continue
                    old=(self.previous or {}).get('network',{}).get(name)
                    state=states.get(name)
                    rows.append({'name':name,'is_up':bool(state and state.isup),'sent_bytes':counter.bytes_sent,'received_bytes':counter.bytes_recv,'upload_bps':rate(counter.bytes_sent,old.bytes_sent,elapsed) if old else None,'download_bps':rate(counter.bytes_recv,old.bytes_recv,elapsed) if old else None})
                default=None
                try:
                    for line in Path('/proc/net/route').read_text().splitlines()[1:]:
                        fields=line.split()
                        if fields[1]=='00000000' and int(fields[3],16)&2:default=fields[0];break
                except (OSError,ValueError,IndexError):pass
                candidates=[r for r in rows if r['is_up']]
                chosen=next((r for r in candidates if r['name']==default),None) or (max(candidates,key=lambda r:r['sent_bytes']+r['received_bytes']) if candidates else None)
                oldio=(self.previous or {}).get('disk')
                try:load=list(p.getloadavg())
                except (AttributeError,OSError):load=None
                cpu=p.cpu_percent(interval=None) if self.previous else None
                memory_used=vm.total-vm.available
                self.latest={'available':True,'status':'正常','timestamp':stamp,'sample_interval':5,'platform':platform.system(),'cpu':{'percent':cpu,'cores':p.cpu_count() or 1,'load_average':load},'memory':{'total':vm.total,'used':memory_used,'available':vm.available,'percent':round(memory_used/max(vm.total,1)*100,1)},'disk':{'mount':'/','total':disk.total,'used':disk.used,'free':disk.free,'percent':disk.percent,'read_bps':rate(io.read_bytes,oldio.read_bytes,elapsed) if io and oldio else None,'write_bps':rate(io.write_bytes,oldio.write_bytes,elapsed) if io and oldio else None},'network':{'interface':chosen['name'] if chosen else None,'upload_bps':chosen['upload_bps'] if chosen else None,'download_bps':chosen['download_bps'] if chosen else None,'interfaces':rows},'uptime_seconds':max(0,stamp-int(p.boot_time()))}
                self.history.append({'ts':stamp,'cpu':cpu,'memory':self.latest['memory']['percent'],'upload':self.latest['network']['upload_bps'],'download':self.latest['network']['download_bps']})
                self.previous={'clock':now,'network':net,'disk':io}
            except Exception:
                self.latest={**self.latest,'available':False,'status':'资源采集失败，保留上次数据'}
    def snapshot(self):
        with self.lock:return copy.deepcopy({**self.latest,'history':list(self.history)})
    def start(self):
        self.sample()
        def poll():
            if self.api:self.api.cpu_percent(interval=None)
            while True:time.sleep(5);self.sample()
        threading.Thread(target=poll,daemon=True).start()
