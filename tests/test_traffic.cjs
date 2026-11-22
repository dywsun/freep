const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
const context={setInterval,clearInterval};vm.createContext(context);vm.runInContext(fs.readFileSync(require.resolve('../frontend/traffic.js'),'utf8'),context);
async function main(){
 assert.equal(context.formatTraffic(1024),'1.00 KB');assert.equal(context.formatTraffic(0),'0 B');
 const now=Date.UTC(2026,10,22,12),hour=now/1000;
 const series=context.trafficSeries([[hour,'uplink',100],[hour,'downlink',900],[hour-3600,'uplink',20]],now);
 assert.equal(series.length,24);assert.equal(series[23].upload,100);assert.equal(series[23].download,900);assert.equal(series[22].upload,20);
 let scheduled,cancelled=0,calls=0,applied=0,errors=0,active=true,resolve,reject;
 const poller=context.createTrafficPoller({fetchSnapshot:()=>{calls++;return new Promise((a,b)=>{resolve=a;reject=b})},applySnapshot:()=>applied++,isActive:()=>active,onError:()=>errors++,schedule:(fn,ms)=>{assert.equal(ms,5000);scheduled=fn;return 7},cancel:id=>{assert.equal(id,7);cancelled++}});
 poller.start();poller.start();assert.equal(typeof scheduled,'function');
 const first=poller.refresh();assert.equal(await poller.refresh(),false);assert.equal(calls,1);resolve({});assert.equal(await first,true);assert.equal(applied,1);
 active=false;assert.equal(await poller.refresh(),false);assert.equal(calls,1);
 active=true;const failing=poller.refresh();reject(Error('network failed'));assert.equal(await failing,false);assert.equal(errors,1);assert.equal(applied,1,'failed request preserves previous data');
 const late=poller.refresh();poller.stop();resolve({});assert.equal(await late,false);assert.equal(applied,1,'logout discards late response');assert.equal(cancelled,1);
 console.log('Traffic formatting, separate curves, polling, visibility, failure and logout checks passed.');
}
main().catch(error=>{console.error(error);process.exitCode=1});
