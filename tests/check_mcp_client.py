import asyncio,sys,unittest
from contextlib import asynccontextmanager
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'backend'))
from knowflow.services.mcp_client import *
from knowflow.services.mcp_client import _PinnedTransport

class Fake:
 def __init__(self): self.init=0; self.calls=0; self.closed=False
 async def initialize(self): self.init+=1
 async def list_tools(self,**kw): return {'tools':[{'name':'echo','description':'x','inputSchema':{},'annotations':{'readOnlyHint':True}}]}
 async def call_tool(self,n,a): self.calls+=1; return {'content':[{'type':'text','text':'ok'},{'type':'image','data':'SECRET'}], 'structuredContent':{'x':1}}
class T(unittest.TestCase):
 def test_names_examples_and_hash(self):
  self.assertEqual(model_tool_name('srv','echo'),'mcp__srv__echo'); self.assertEqual(model_tool_name('中文','工具'),'mcp__server__server'); self.assertEqual(model_tool_name('a'*100,'b'*100),model_tool_name('a'*100,'b'*100)); self.assertLessEqual(len(model_tool_name('a'*100,'b'*100)),64)
 def test_paging_fields_and_limits(self):
  class P(Fake):
   n=0
   async def list_tools(self,**kw):
    self.n+=1; return {'tools':[{'name':'echo'+str(self.n),'description':'x'*2000,'inputSchema':{},'annotations':{'readOnlyHint':True,'destructiveHint':False}}], 'nextCursor':None if self.n>1 else 'x'}
  f=P(); c=McpRemoteClient('s','https://x',session_factory=lambda u,h:f,resolver=lambda *a:[(0,0,0,'x',('8.8.8.8',443))]); s=asyncio.run(c.discover_tools()); self.assertEqual(f.n,2); self.assertEqual(s[0]['name'],'echo1'); self.assertEqual(len(s[0]['description']),1000)
 def test_invalid_schema_keeps_snapshot(self):
  f=Fake(); c=McpRemoteClient('s','https://x',session_factory=lambda u,h:f,resolver=lambda *a:[(0,0,0,'x',('8.8.8.8',443))]); asyncio.run(c.discover_tools()); old=c.tool_snapshot.copy(); f.list_tools=lambda **kw: asyncio.sleep(0,result={'tools':[{'name':'bad','inputSchema':None}]}); self.assertRaises(McpClientError,lambda: asyncio.run(c.discover_tools())); self.assertEqual(c.tool_snapshot,old)
 def test_collision_and_discovery_limit(self):
  f=Fake(); f.list_tools=lambda **kw: asyncio.sleep(0,result={'tools':[{'name':'a b','inputSchema':{}},{'name':'a-b','inputSchema':{}}]}); c=McpRemoteClient('s','https://x',session_factory=lambda u,h:f,resolver=lambda *a:[(0,0,0,'x',('8.8.8.8',443))]); self.assertRaises(McpClientError,lambda: asyncio.run(c.discover_tools()))
 def test_normalize_and_call_limit(self):
  x=normalize_result({'content':[{'type':'text','text':'abcdef'},{'type':'image','data':'SECRET'}],'structuredContent':'x','isError':True},max_chars=3); self.assertEqual(x['content'],'abc'); self.assertNotIn('SECRET',str(x)); self.assertTrue(x['isError']); self.assertIsNone(x['structuredContent'])
  self.assertRaises(McpClientError,normalize_result,{'content':[{'type':'text','text':'x'*20}]},4000,5)
 def test_http_factory_args(self):
  seen={}
  class C:
   async def initialize(self): pass
  async def fac(u,h): seen.update(u=u,h=h); return C()
  c=McpRemoteClient('s','https://x',headers={'X-A':'b'},session_factory=fac,resolver=lambda *a:[(0,0,0,'x',('8.8.8.8',443))]); co=asyncio.run(c._connect()); self.assertEqual(seen['h'],{'X-A':'b'}); asyncio.run(co.stack.aclose()); asyncio.run(co.http.aclose())
 def test_pool_two_servers_and_close(self):
  fs=[Fake(),Fake()]; cs=[McpRemoteClient(str(i),'https://x',session_factory=lambda u,h,f=f:f,resolver=lambda *a:[(0,0,0,'x',('8.8.8.8',443))]) for i,f in enumerate(fs)]
  with McpRunSessionPool(server_loader=lambda sid:cs[int(sid)]) as p: p.call_tool('0','echo'); p.call_tool('0','echo'); p.call_tool('1','echo')
  self.assertEqual(fs[0].calls,2); self.assertEqual(fs[1].calls,1)
 def test_pool_closes_session_in_task_that_opened_it(self):
  f=Fake(); state={}
  @asynccontextmanager
  async def factory(url,headers):
   state['owner']=asyncio.current_task()
   try: yield f
   finally:
    state['same_task']=asyncio.current_task() is state['owner']
    if not state['same_task']: raise RuntimeError('session closed from a different task')
  c=McpRemoteClient('s','https://x',session_factory=factory,resolver=lambda *a:[(0,0,0,'x',('8.8.8.8',443))])
  with McpRunSessionPool(server_loader=lambda sid:c) as p: self.assertEqual(p.call_tool('s','echo')['content'],'ok')
  self.assertTrue(state.get('same_task'))
 def test_dict_loader(self):
  made=[]
  def cf(*a,**k): made.append((a,k)); return cs[0]
  cs=[McpRemoteClient('s','https://x',session_factory=lambda u,h:Fake(),resolver=lambda *a:[(0,0,0,'x',('8.8.8.8',443))])]
  with McpRunSessionPool(server_loader=lambda s:{'id':'s','url':'https://x','name':'N','credentials':{'headers':{'A':'b'}}},client_factory=cf,max_response_bytes=123) as p: p.call_tool('s','echo')
  self.assertEqual(made[0][1]['headers'],{'A':'b'}); self.assertEqual(made[0][1]['max_response_bytes'],123)
 def test_strict_structured_bytes(self):
  with self.assertRaises(McpClientError) as e: normalize_result({'structuredContent':{'x':b'bad'}})
  self.assertEqual(e.exception.code,'mcp_invalid_response'); self.assertNotIn('bad',str(e.exception))
 def test_empty_name_and_page_limit(self):
  f=Fake(); f.list_tools=lambda **kw: asyncio.sleep(0,result={'tools':[{'name':'','inputSchema':{}}]}); c=McpRemoteClient('s','https://x',session_factory=lambda u,h:f,resolver=lambda *a:[(0,0,0,'x',('8.8.8.8',443))]); old={'x':1}; c.tool_snapshot=old; self.assertRaises(McpClientError,lambda:asyncio.run(c.discover_tools())); self.assertEqual(c.tool_snapshot,old)
 def test_factory_close_once(self):
  class S(Fake):
   async def aclose(self): self.closed=True
  s=S(); c=McpRemoteClient('s','https://x',session_factory=lambda u,h:s,resolver=lambda *a:[(0,0,0,'x',('8.8.8.8',443))]); co=asyncio.run(c._connect()); asyncio.run(co.stack.aclose()); asyncio.run(co.http.aclose()); self.assertTrue(s.closed)
 def test_pool_thread_mismatch(self):
  import threading
  p=McpRunSessionPool(server_loader=lambda s:None); out=[]
  def run():
   try: p.call_tool('s','x')
   except Exception as e: out.append(e)
  t=threading.Thread(target=run); t.start(); t.join(); self.assertTrue(out and isinstance(out[0],McpClientError)); p.close()
 def test_pinned_transport(self):
  class D:
   async def handle_async_request(self,r): self.r=r; return r
  d=D(); tr=_PinnedTransport(d,lambda h,p:['93.184.216.34']); req=httpx.Request('GET','https://example.com/a'); asyncio.run(tr.handle_async_request(req)); self.assertEqual(d.r.url.host,'93.184.216.34'); self.assertEqual(d.r.headers['host'],'example.com'); self.assertEqual(d.r.extensions['sni_hostname'],'example.com')
 def test_pinned_transport_recheck_blocks(self):
  class D:
   called=False
   async def handle_async_request(self,r): self.called=True
  d=D(); n=[0]
  def res(h,p): n[0]+=1; return ['93.184.216.34'] if n[0]==1 else ['10.0.0.1']
  tr=_PinnedTransport(d,res); req=httpx.Request('GET','https://example.com'); asyncio.run(tr.handle_async_request(req)); d.called=False; self.assertRaises(ValueError,lambda:asyncio.run(tr.handle_async_request(req))); self.assertFalse(d.called)
 def test_cursor_page_limit(self):
  f=Fake(); f.i=0
  async def lt(**kw): f.i+=1; return {'tools':[],'nextCursor':str(f.i)}
  f.list_tools=lt; c=McpRemoteClient('s','https://x',session_factory=lambda u,h:f,resolver=lambda *a:[(0,0,0,'x',('8.8.8.8',443))]); self.assertRaises(McpClientError,lambda:asyncio.run(c.discover_tools()))
 def test_invalidate_reconnect(self):
  fs=[Fake(),Fake()]; i=[0]
  def load(s): x=fs[i[0]]; i[0]+=1; return McpRemoteClient('s','https://x',session_factory=lambda u,h,f=x:f,resolver=lambda *a:[(0,0,0,'x',('8.8.8.8',443))])
  p=McpRunSessionPool(server_loader=load); p.call_tool('s','echo'); p.invalidate('s'); p.call_tool('s','echo'); p.close(); self.assertEqual(i[0],2)
 def test_pinned_unread_stream(self):
  class S(httpx.AsyncByteStream):
   async def __aiter__(self): yield b'raw-bytes'
  class D:
   async def handle_async_request(self,r): self.data=b''.join([x async for x in r.stream]); return httpx.Response(200,request=r)
  d=D(); tr=_PinnedTransport(d,lambda h,p:['93.184.216.34']); asyncio.run(tr.handle_async_request(httpx.Request('POST','https://example.com',content=S()))); self.assertEqual(d.data,b'raw-bytes')
 def test_default_connect_uses_pinned(self):
  import knowflow.services.mcp_client as m
  seen={}
  class A:
   def __init__(self,**kw): seen.update(kw)
   async def aclose(self): pass
  old=m.httpx.AsyncClient; m.httpx.AsyncClient=A
  class S(Fake): pass
  try:
   c=McpRemoteClient('s','https://x',session_factory=lambda u,h:S(),resolver=lambda *a:[(0,0,0,'x',('8.8.8.8',443))]); co=asyncio.run(c._connect()); self.assertIsInstance(seen['transport'],_PinnedTransport); self.assertIsInstance(seen['transport'].delegate,httpx.AsyncHTTPTransport); asyncio.run(co.stack.aclose()); asyncio.run(co.http.aclose())
  finally: m.httpx.AsyncClient=old
 def test_pinned_aclose_once(self):
  class D:
   def __init__(self): self.n=0
   async def aclose(self): self.n+=1
  d=D(); asyncio.run(_PinnedTransport(d,lambda h,p:['93.184.216.34']).aclose()); self.assertEqual(d.n,1)
 def test_pinned_host_authority_and_no_mutation(self):
  class D:
   async def handle_async_request(self,r): self.r=r; return httpx.Response(200,request=r)
  d=D(); req=httpx.Request('GET','https://example.com:8443/x'); original=dict(req.headers); asyncio.run(_PinnedTransport(d,lambda h,p:['93.184.216.34']).handle_async_request(req)); self.assertEqual(d.r.headers['host'],'example.com:8443'); self.assertEqual(dict(req.headers),original)
 def test_name_and_normalize(self):
  self.assertLessEqual(len(model_tool_name('a'*100,'b'*100)),64)
  x=normalize_result({'content':[{'type':'image','data':'x'}]}); self.assertNotIn('data',str(x)); self.assertIsNone(x['structuredContent'])
 def test_discover_and_pool(self):
  f=Fake()
  async def factory(url,headers): return f
  c=McpRemoteClient('s','https://example.com',session_factory=factory,resolver=lambda h,p:[(0,0,0,'x',('8.8.8.8',p))])
  # injected factory still validates DNS
  snap=asyncio.run(c.discover_tools()); self.assertEqual(snap[0]['remoteName'],'echo'); self.assertEqual(snap[0]['annotations']['readOnlyHint'],True)
  with McpRunSessionPool(server_loader=lambda sid:c) as p:
   self.assertEqual(p.call_tool('s','echo')['content'],'ok'); self.assertEqual(p.call_tool('s','echo')['content'],'ok')
  self.assertEqual(f.init,3); self.assertEqual(f.calls,2)
if __name__=='__main__': unittest.main()
