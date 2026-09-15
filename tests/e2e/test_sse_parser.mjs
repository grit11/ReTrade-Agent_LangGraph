// SSE/API 解析器回归测试，使用本地 Fetch 替身覆盖分片、缺失回执和错误响应。

import assert from 'node:assert/strict';
import {streamChat,api} from '../../frontend/api.js';
const encoder=new TextEncoder();
const lines='data: {"type":"stage","stage":"triage"}\r\n\r\ndata: {"type":"token","content":"退货规则","buffered":true}\n\ndata: {"type":"done","reply":"退货规则"}\n\n';
const bytes=encoder.encode(lines);
globalThis.fetch=async()=>new Response(new ReadableStream({start(controller){for(let i=0;i<bytes.length;i+=7)controller.enqueue(bytes.slice(i,i+7));controller.close();}}),{status:200});
let events=[];await streamChat({},e=>events.push(e));assert.equal(events.length,3);assert.equal(events[1].content,'退货规则');
globalThis.fetch=async()=>new Response('data: {"type":"stage"}\n\n',{status:200});
await assert.rejects(()=>streamChat({},()=>{}),/未收到处理回执/);
globalThis.fetch=async()=>new Response('data: {"type":"error","message":"不允许"}\n\n',{status:200});
await assert.rejects(()=>streamChat({},()=>{}),/不允许/);
globalThis.fetch=async()=>new Response(JSON.stringify({error:{message:'未登录',code:'UNAUTHORIZED'}}),{status:401,headers:{'Content-Type':'application/json'}});
await assert.rejects(()=>api('/test'),/未登录/);
console.log('4 JS SSE/API parser assertions passed. Fetch is a local test double.');
