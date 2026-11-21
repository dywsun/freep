// Optional decoder: QR_DECODER_MODULE=/path/to/jsQR.js node tests/test_qr.cjs
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const qrcode=require('../frontend/vendor/qrcode.js');
const context={qrcode};vm.createContext(context);vm.runInContext(fs.readFileSync(require.resolve('../frontend/share.js'),'utf8'),context);
const decoder=process.env.QR_DECODER_MODULE?require(process.env.QR_DECODER_MODULE):null;
const fixtures=[
 'https://free.dywsun.dpdns.org:18898/freedom-network/sub/long-random-user-token?format=mihomo',
 'vmess://'+Buffer.from(JSON.stringify({v:'2',ps:'用户甲 · VMess',add:'node.example.com',port:'8880',id:'22889564-6101-4e00-a64a-d79184d59891',aid:'0',net:'ws',path:'shared-entry-id-vm',host:'www.bing.com',tls:''})).toString('base64'),
 'tuic://22889564-6101-4e00-a64a-d79184d59891:independent-password-123@node.example.com:32786?sni=www.bing.com&alpn=h3&congestion_control=bbr#TUIC',
 '二维码 UTF-8 测试 🛰️'
];
for(const text of fixtures){
 const qr=context.makeShareQr(text),count=qr.getModuleCount(),scale=5,quiet=4,size=(count+quiet*2)*scale;
 assert(count>=21);assert.equal(typeof qr.isDark(0,0),'boolean');
 if(decoder){
  const rgba=new Uint8ClampedArray(size*size*4);rgba.fill(255);
  for(let row=0;row<count;row++)for(let col=0;col<count;col++)if(qr.isDark(row,col))for(let dy=0;dy<scale;dy++)for(let dx=0;dx<scale;dx++){
   const offset=(((row+quiet)*scale+dy)*size+(col+quiet)*scale+dx)*4;rgba[offset]=rgba[offset+1]=rgba[offset+2]=0;
  }
  const result=decoder(rgba,size,size);assert(result,'QR must decode');assert.equal(result.data,text);
 }
}
assert.throws(()=>context.makeShareQr(''),/分享内容为空/);
assert.throws(()=>context.makeShareQr('x'.repeat(10000)),/分享内容过长/);
console.log(`QR fixtures passed${decoder?' (decoded original payloads)':''}.`);
