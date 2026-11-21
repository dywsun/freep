/* Local-only QR rendering. Payloads are never sent to a QR service. */
function makeShareQr(text) {
  if (typeof text !== 'string' || !text.length) throw Error('分享内容为空');
  qrcode.stringToBytes = qrcode.stringToBytesFuncs['UTF-8'];
  const qr = qrcode(0, 'M');
  qr.addData(text, 'Byte');
  try { qr.make(); } catch { throw Error('分享内容过长，无法生成二维码，请复制链接'); }
  return qr;
}
function showShareQr(text, title, filename, isDemo=false) {
  showModal(`<h2>${esc(title)}</h2><p class="subtitle">${isDemo?'演示二维码，不能连接真实节点。':'包含访问凭据，仅分享给对应用户。扫码导入取决于客户端支持。'}</p><div id="qrContainer" class="qr-container"></div><label>分享链接<textarea id="qrLink" class="qr-link" rows="3" readonly></textarea></label><p id="qrError" class="form-error" role="alert"></p><div class="actions"><button type="button" class="btn" id="qrCopy">复制链接</button><button type="button" class="btn primary" id="qrDownload">下载 PNG</button>${btn('关闭',"document.querySelector('#modal').close()")}</div>`);
  const link=$('#qrLink');link.value=text;
  $('#qrCopy').onclick=async()=>{try{await navigator.clipboard.writeText(text);toast('分享链接已复制')}catch{link.focus();link.select();toast('请手动复制选中的链接')}};
  try {
    const qr=makeShareQr(text), count=qr.getModuleCount(), quiet=4, scale=Math.max(4,Math.floor(512/(count+quiet*2)));
    const canvas=document.createElement('canvas');canvas.width=canvas.height=(count+quiet*2)*scale;
    canvas.setAttribute('role','img');canvas.setAttribute('aria-label',title+'二维码');
    const ctx=canvas.getContext('2d');ctx.fillStyle='#ffffff';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.fillStyle='#000000';
    for(let row=0;row<count;row++)for(let col=0;col<count;col++)if(qr.isDark(row,col))ctx.fillRect((col+quiet)*scale,(row+quiet)*scale,scale,scale);
    $('#qrContainer').append(canvas);
    $('#qrDownload').onclick=()=>{const a=document.createElement('a');a.download=filename;a.href=canvas.toDataURL('image/png');document.body.append(a);a.click();a.remove();toast('二维码 PNG 已生成')};
  } catch(e) {$('#qrError').textContent=e.message;$('#qrDownload').disabled=true;}
}
function showSubscriptionQr(format) {
  const u=users[Number($('#subUser')?.value||0)];if(!u){toast('请先选择用户');return}
  if(window.RELAY_LIVE&&!u.effective){toast('此用户订阅当前不可用');return}
  const url=window.RELAY_LIVE?subscriptionUrl(format):`https://panel.example.com/sub/demo-${encodeURIComponent(u.id)}?format=${encodeURIComponent(format)}`;
  showShareQr(url,`${u.name} · ${format} 订阅`,'relay-subscription-'+format+'.png',!window.RELAY_LIVE);
}
function demoNodeShares(u) {
  return protocols.filter(p=>p.active&&u.credentials[p.name]).map(p=>{
    const c=u.credentials[p.name],tag=encodeURIComponent(`${u.name} · ${p.name}`);let uri;
    if(p.name==='VMess'){
      const config={v:'2',ps:`${u.name} · VMess（演示）`,add:'node.example.com',port:String(p.port),id:c.uuid,aid:'0',scy:'auto',net:'ws',type:'none',host:'www.bing.com',path:'demo-entry-vm',tls:''};
      uri='vmess://'+btoa(String.fromCharCode(...new TextEncoder().encode(JSON.stringify(config))));
    } else if(p.name==='TUIC v5')uri=`tuic://${c.uuid}:${encodeURIComponent(c.password)}@node.example.com:${p.port}?sni=www.bing.com&alpn=h3&congestion_control=bbr&allowInsecure=1#${tag}`;
    else return null;
    return {protocol:p.name,uri};
  }).filter(Boolean);
}
async function showUserNodeCodes(i) {
  const u=users[i];if(!u)return;
  if(!u.active||(window.RELAY_LIVE&&!u.effective)){toast('此用户当前不可用');return}
  try {
    let nodes;
    if(window.RELAY_LIVE){nodes=(await liveRequest('/api/share?id='+encodeURIComponent(u.id))).nodes}
    else nodes=demoNodeShares(u);
    if(!nodes.length){toast(window.RELAY_LIVE?'没有已启用且授权的节点':'演示模式仅提供 VMess、TUIC 单节点二维码');return}
    showModal(`<h2>${esc(u.name)} · 分享节点</h2><p class="subtitle">单节点二维码包含该用户的独立凭据。${window.RELAY_LIVE?'':'此处为演示数据。'}</p><label>选择协议<select id="qrProtocol" aria-label="选择分享协议">${nodes.map((n,index)=>`<option value="${index}">${esc(n.protocol)}</option>`).join('')}</select></label><div class="actions"><button type="button" class="btn primary" id="qrShowNode">显示二维码</button>${btn('关闭',"document.querySelector('#modal').close()")}</div>`);
    $('#qrShowNode').onclick=()=>{const node=nodes[Number($('#qrProtocol').value)];showShareQr(node.uri,`${u.name} · ${node.protocol}`,'relay-node-'+node.protocol.replace(/[^a-z0-9]/gi,'-')+'.png',!window.RELAY_LIVE)};
  } catch(e){toast(e.message)}
}
