// Local real-API preview. Never starts a public listener or installs Cloudflare resources.
import http from 'node:http';
import {readFileSync,mkdirSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {fileURLToPath} from 'node:url';
import {d1} from '../tests/worker_d1.mjs';
import worker from '../worker-service/dist/worker.js';
const root=fileURLToPath(new URL('../',import.meta.url));mkdirSync(root+'.local',{recursive:true});
const database=new DatabaseSync(root+'.local/worker-gateway-preview.db');database.exec(readFileSync(root+'worker-service/schema.sql','utf8'));
const env={DB:d1(database)};
http.createServer(async(req,res)=>{try{const headers=new Headers();for(const [k,v] of Object.entries(req.headers))if(v)headers.set(k,Array.isArray(v)?v.join(','):v);headers.set('CF-Connecting-IP','127.0.0.1');const chunks=[];let length=0;for await(const part of req){length+=part.length;if(length>16384){res.writeHead(413);res.end();return}chunks.push(part)}
const request=new Request('http://127.0.0.1:18094'+req.url,{method:req.method,headers,...(!['GET','HEAD'].includes(req.method)?{body:Buffer.concat(chunks)}:{})});
const result=await worker.fetch(request,env,{waitUntil(p){p.catch(()=>{})}});res.writeHead(result.status,Object.fromEntries(result.headers));if(result.body){const reader=result.body.getReader();for(;;){const {done,value}=await reader.read();if(done)break;res.write(value)}}res.end();
}catch{res.writeHead(500);res.end('Local preview error')}}).listen(18094,'127.0.0.1',()=>console.log('Worker API preview: http://127.0.0.1:18094/ (account: dywsun; set your own password on first visit)'));
