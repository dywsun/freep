from pathlib import Path
import sys
from types import SimpleNamespace as N
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from monitor import SystemMonitor,rate

class Fake:
    def __init__(self):self.sent=1000;self.recv=2000;self.read=300;self.write=600
    def cpu_percent(self,interval=None):return 25
    def cpu_count(self):return 2
    def virtual_memory(self):return N(total=1000,available=600)
    def disk_usage(self,path):return N(total=2000,used=800,free=1200,percent=40)
    def disk_io_counters(self):return N(read_bytes=self.read,write_bytes=self.write)
    def net_io_counters(self,pernic=True):return {'eth0':N(bytes_sent=self.sent,bytes_recv=self.recv),'lo':N(bytes_sent=99999,bytes_recv=99999)}
    def net_if_stats(self):return {'eth0':N(isup=True)}
    def getloadavg(self):return (0.1,0.2,0.3)
    def boot_time(self):return 100

class MonitorTests(unittest.TestCase):
    def test_rates_memory_and_interfaces(self):
        fake=Fake();ticks=iter([10,15,20]);m=SystemMonitor(fake,clock=lambda:next(ticks))
        m.sample();s=m.snapshot();self.assertIsNone(s['cpu']['percent']);self.assertIsNone(s['network']['upload_bps']);self.assertEqual(s['memory']['used'],400)
        fake.sent+=500;fake.recv+=1000;fake.read+=250;fake.write+=750
        m.sample();s=m.snapshot();self.assertEqual(s['cpu']['percent'],25);self.assertEqual(s['network']['upload_bps'],100);self.assertEqual(s['network']['download_bps'],200);self.assertEqual(s['disk']['write_bps'],150)
        self.assertEqual(len(s['network']['interfaces']),1);self.assertEqual(len(s['history']),2)
        fake.sent=0;fake.recv=0;m.sample();self.assertEqual(m.snapshot()['network']['upload_bps'],0)
    def test_no_negative_rates_or_external_mutation(self):
        self.assertEqual(rate(10,20,5),0);self.assertIsNone(rate(10,2,0))
        fake=Fake();m=SystemMonitor(fake,clock=lambda:10);m.sample();s=m.snapshot();s['memory']['used']=999
        self.assertEqual(m.snapshot()['memory']['used'],400)
