"""Defensive MCP remote client adapter."""
from __future__ import annotations
import asyncio, hashlib, json, re, inspect, threading
from contextlib import AsyncExitStack
from datetime import timedelta
import httpx
try:
 from mcp import ClientSession
 from mcp.client.streamable_http import streamable_http_client
except ModuleNotFoundError as exc:
 if exc.name != "mcp": raise
 ClientSession = None; streamable_http_client = None
from ..config import MCP_MAX_RESPONSE_BYTES
from .mcp_security import PinnedAsyncTransport, validate_remote_url, validate_static_headers

_PinnedTransport = PinnedAsyncTransport

class McpClientError(Exception):
 def __init__(self,message,code="mcp_client_error"): super().__init__(message); self.code=code
def _get(x,k,d=None): return x.get(k,d) if isinstance(x,dict) else getattr(x,k,d)
def _size(x):
 try: return len(json.dumps(x,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode())
 except (TypeError, ValueError) as exc: raise McpClientError("invalid structured content","mcp_invalid_response") from exc

def _slug(x,fallback="server"):
 s=re.sub(r"[^A-Za-z0-9_-]+","-",str(x or "")).strip("-") or fallback
 return s
def model_tool_name(server,tool):
 raw=f"mcp__{_slug(server)}__{_slug(tool)}"
 return raw if len(raw)<=64 else raw[:55]+"-"+hashlib.sha256(raw.encode()).hexdigest()[:8]
def normalize_result(result,max_chars=4000,max_response_bytes=MCP_MAX_RESPONSE_BYTES):
 text=[]; types=[]
 for b in (_get(result,"content",[]) or []):
  typ=_get(b,"type")
  if typ=="text": text.append(str(_get(b,"text", "")))
  elif typ: types.append({"type":str(typ)})
 sc=_get(result,"structuredContent")
 out={"structuredContent":sc if isinstance(sc,(dict,list)) else None,"content":"".join(text),"isError":bool(_get(result,"isError",False))}
 if types: out["contentTypes"]=types
 if _size(out)>max_response_bytes: raise McpClientError("mcp_response_too_large","mcp_response_too_large")
 out["content"]=out["content"][:max_chars]; return out
class _Conn:
 def __init__(self,s,stack,http): self.session,self.stack,self.http=s,stack,http
class McpRemoteClient:
 def __init__(self,server_id,server_url,headers=None,server_name=None,session_factory=None,max_response_bytes=None,max_chars=4000,resolver=None,allow_private=False,connect_timeout=10,request_timeout=30,base_transport=None,**kwargs):
  if kwargs: raise TypeError(f"unknown kwargs: {','.join(kwargs)}")
  self.server_id=server_id; self.server_url=server_url; self.server_name=server_name or server_id; self.headers=validate_static_headers(headers or {}); self.session_factory=session_factory; self.max_response_bytes=max_response_bytes if max_response_bytes is not None else MCP_MAX_RESPONSE_BYTES; self.max_chars=max_chars; self.resolver=resolver; self.allow_private=allow_private; self.connect_timeout=connect_timeout; self.request_timeout=request_timeout; self.base_transport=base_transport; self.tool_snapshot={}
 async def _connect(self):
  validate_remote_url(self.server_url,resolver=self.resolver,allow_private=self.allow_private)
  timeout=httpx.Timeout(self.request_timeout,connect=self.connect_timeout)
  delegate=self.base_transport or httpx.AsyncHTTPTransport(trust_env=False)
  transport=PinnedAsyncTransport(delegate,self.resolver,self.allow_private)
  http=httpx.AsyncClient(headers=self.headers,trust_env=False,follow_redirects=False,timeout=timeout,transport=transport)
  stack=AsyncExitStack(); await stack.__aenter__()
  try:
   if self.session_factory:
    made=self.session_factory(self.server_url,self.headers)
    if hasattr(made,'__aenter__'): s=await stack.enter_async_context(made)
    else:
     s=await made if inspect.isawaitable(made) else made
     if hasattr(s,'aclose'): stack.push_async_callback(s.aclose)
     elif hasattr(s,'close'): stack.callback(s.close)
   else:
    if not ClientSession: raise McpClientError("mcp_sdk_unavailable")
    transport=await stack.enter_async_context(streamable_http_client(self.server_url,http_client=http))
    s=await stack.enter_async_context(ClientSession(transport[0],transport[1],read_timeout_seconds=timedelta(seconds=self.request_timeout)))
   await s.initialize(); return _Conn(s,stack,http)
  except Exception:
   await stack.aclose(); await http.aclose(); raise
 async def discover_tools(self):
  c=await self._connect()
  try:
   snap={}; cursor=None; seen=set(); pages=0; total=0
   while True:
    r=await c.session.list_tools(cursor=cursor) if cursor is not None else await c.session.list_tools()
    pages+=1
    if pages>100: raise McpClientError("mcp_discovery_limit","mcp_discovery_limit")
    for t in (_get(r,"tools",[]) or []):
     total+=1
     if total>1000: raise McpClientError("mcp_discovery_limit","mcp_discovery_limit")
     remote=str(_get(t,"name", ""));
     if not remote: raise McpClientError("invalid_tool_name","invalid_tool_name")
     model=model_tool_name(self.server_name,remote)
     if model in snap: raise McpClientError("tool_name_conflict","tool_name_conflict")
     schema=_get(t,"inputSchema",{})
     if not isinstance(schema,dict): raise McpClientError("invalid_input_schema","invalid_input_schema")
     item={"name":remote,"modelName":model,"remoteName":remote,"serverId":self.server_id,"serverName":self.server_name,"description":str(_get(t,"description","") or "")[:1000],"inputSchema":schema}
     ann=_get(t,"annotations")
     if ann is not None: item["annotations"]={k:_get(ann,k) for k in ("title","readOnlyHint","destructiveHint","idempotentHint","openWorldHint") if _get(ann,k) is not None}
     snap[model]=item
    cursor=_get(r,"nextCursor")
    if not cursor or cursor in seen: break
    seen.add(cursor)
   if _size(snap)>self.max_response_bytes: raise McpClientError("mcp_response_too_large","mcp_response_too_large")
   self.tool_snapshot=snap; return list(snap.values())
  finally: await c.stack.aclose(); await c.http.aclose()
class McpRunSessionPool:
 def __init__(self,server_loader=None,oauth=None,connect_timeout=10,request_timeout=30,max_response_bytes=None,max_chars=4000,resolver=None,allow_private=False,client_factory=None,**kwargs):
  if kwargs: raise TypeError(f"unknown kwargs: {','.join(kwargs)}")
  self.server_loader=server_loader; self.oauth=oauth; self.params=dict(connect_timeout=connect_timeout,request_timeout=request_timeout,max_response_bytes=max_response_bytes,max_chars=max_chars,resolver=resolver,allow_private=allow_private); self.client_factory=client_factory or McpRemoteClient; self._clients={}; self._loop=asyncio.new_event_loop(); self._thread=threading.get_ident()
 def __enter__(self): return self
 def __exit__(self,*exc): self.close()
 def _make(self,sid):
  x=self.server_loader(sid) if self.server_loader else sid
  if isinstance(x,McpRemoteClient): return x
  if not isinstance(x,dict): return x
  creds=x.get('credentials') or {}; headers=creds.get('headers') or {}
  return self.client_factory(x.get('id',sid),x['url'],headers=headers,server_name=x.get('name') or sid,**self.params)
 def _check_thread(self):
  if threading.get_ident()!=self._thread: raise McpClientError("mcp_pool_thread_mismatch","mcp_pool_thread_mismatch")
 def call_tool(self,server_id,remote_name,args=None): self._check_thread(); return self._loop.run_until_complete(self._call(server_id,remote_name,args or {}))
 async def _call(self,sid,remote,args):
  if sid not in self._clients: self._clients[sid]=self._make(sid)
  client=self._clients[sid]; connection=await client._connect()
  try:
   r=await connection.session.call_tool(remote,args)
   return normalize_result(r,self.params['max_chars'],client.max_response_bytes)
  finally:
   try: await connection.stack.aclose()
   finally: await connection.http.aclose()
 def invalidate(self,server_id):
  self._check_thread()
  if server_id in self._clients: self._loop.run_until_complete(self._drop(server_id))
 async def _drop(self,sid):
  client=self._clients.pop(sid,None)
  if client and hasattr(client,'aclose'): await client.aclose()
 def close(self):
  self._check_thread()
  if not self._loop.is_closed(): self._loop.run_until_complete(self._aclose()); self._loop.close()
 async def _aclose(self):
  for sid in reversed(list(self._clients)):
   client=self._clients[sid]
   if hasattr(client,'aclose'): await client.aclose()
  self._clients.clear()
