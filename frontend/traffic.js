/* Traffic-only polling: no credentials, no page reloads, no overlapping requests. */
function formatTraffic(bytes) {
  let value=Math.max(0,Number(bytes)||0),unit=0;const units=['B','KB','MB','GB','TB'];
  while(value>=1024&&unit<units.length-1){value/=1024;unit++}
  return `${value.toFixed(unit?2:0)} ${units[unit]}`;
}
function trafficSeries(history,now=Date.now()) {
  const hour=Math.floor(now/3600000)*3600;
  return Array.from({length:24},(_,i)=>{const ts=hour-(23-i)*3600;return {ts,upload:history.filter(r=>r[0]===ts&&r[1]==='uplink').reduce((a,r)=>a+r[2],0),download:history.filter(r=>r[0]===ts&&r[1]==='downlink').reduce((a,r)=>a+r[2],0)}});
}
function createTrafficPoller({fetchSnapshot,applySnapshot,isActive,onError,interval=5000,schedule=setInterval,cancel=clearInterval}) {
  let timer=null,inflight=false,generation=0;
  async function refresh(){
    if(inflight||!isActive())return false;
    inflight=true;const current=generation;
    try{const snapshot=await fetchSnapshot();if(current!==generation||!isActive())return false;applySnapshot(snapshot);return true}
    catch(error){if(current===generation&&isActive())onError(error);return false}
    finally{inflight=false}
  }
  return {refresh,start(){if(timer===null)timer=schedule(refresh,interval)},stop(){generation++;if(timer!==null)cancel(timer);timer=null}};
}
