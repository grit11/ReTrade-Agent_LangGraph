export class ApiError extends Error {constructor(message,status,code){super(message);this.status=status;this.code=code;}}
export function staffToken(){return sessionStorage.getItem('retrade_staff_token')||'';}
export function setStaffToken(token){if(token)sessionStorage.setItem('retrade_staff_token',token);else sessionStorage.removeItem('retrade_staff_token');}
export async function api(path,{method='GET',body,staff=false,signal}={}){
 const headers={};if(staff&&staffToken())headers['X-Admin-Token']=staffToken();
 if(body&&!(body instanceof FormData)){headers['Content-Type']='application/json';body=JSON.stringify(body);}
 const response=await fetch(path,{method,headers,body,credentials:'same-origin',signal});
 let value;try{value=await response.json();}catch{value={};}
 if(!response.ok)throw new ApiError(value.error?.message|| (typeof value.detail==='string'?value.detail:'请求失败，请检查输入或重试'),response.status,value.error?.code);
 return value;
}
export async function streamChat(body,onEvent,signal){
 const response=await fetch('/api/v1/chat/stream',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),credentials:'same-origin',signal});
 if(!response.ok){let value={};try{value=await response.json();}catch{}throw new ApiError(value.error?.message||'服务暂时不可用',response.status);}
 if(!response.body)throw new Error('当前浏览器不支持流式响应');
 const reader=response.body.getReader();const decoder=new TextDecoder();let buffer='',done=false;
 try{while(true){const part=await reader.read();buffer+=decoder.decode(part.value||new Uint8Array(),{stream:!part.done});buffer=buffer.replace(/\r\n/g,'\n');
   let boundary;while((boundary=buffer.indexOf('\n\n'))!==-1){const block=buffer.slice(0,boundary);buffer=buffer.slice(boundary+2);const data=block.split('\n').filter(x=>x.startsWith('data:')).map(x=>x.slice(5).trimStart()).join('\n');if(!data)continue;
     const event=JSON.parse(data);onEvent(event);if(event.type==='done')done=true;if(event.type==='error')throw new ApiError(event.message||'处理失败',500,event.code);
   }if(part.done)break;
 }if(!done)throw new Error('连接结束但未收到处理回执；重试会复用原 request_id。');}
 finally{try{await reader.cancel();}catch{}reader.releaseLock();}
}
