import asyncio,re
from urllib.parse import parse_qsl,urlencode,urlsplit,urlunsplit
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import RedirectResponse
from ..runtime import *
from ..schemas import McpServerCreate,McpServerUpdate,McpOAuthStartIn
from ..services.mcp_security import validate_remote_url,validate_static_headers
from ..services.mcp_client import McpRemoteClient
from ..services.mcp_oauth import McpOAuthError
router=APIRouter(); NOTION_URL='https://mcp.notion.com/mcp'
def uid(r): return current_user_id(r)
def owned(r,i):
 x=mcp_configs.get_owned(uid(r),i)
 if not x: raise HTTPException(404,'MCP server not found')
 return x
def out(x): return x
def discover(user,s):
 sec=mcp_configs.secret(user,s['id']) or {}; c=sec.get('credentials') or {}; h={}
 if s['authType']=='headers': h.update(c.get('headers') or {})
 elif s['authType']=='oauth': h.update(mcp_oauth.authorization_headers(user,s['id']))
 client=McpRemoteClient(str(s['id']),s['url'],server_name=s['slug'],headers=h,request_timeout=MCP_REQUEST_TIMEOUT,max_response_bytes=MCP_MAX_RESPONSE_BYTES,allow_private=MCP_ALLOW_PRIVATE_NETWORKS)
 return asyncio.run(client.initialize_and_list_tools()) if hasattr(client,'initialize_and_list_tools') else asyncio.run(client.discover_tools())
def oauth_result_url(target,key,value):
 parts=urlsplit(target); query=[(k,v) for k,v in parse_qsl(parts.query,keep_blank_values=True) if k not in ('mcpResult','mcpError')]; query.append((key,value))
 return urlunsplit((parts.scheme,parts.netloc,parts.path,urlencode(query),parts.fragment))
def oauth_default_return_url():
 target=next((item for item in OAUTH_RETURN_ORIGINS if is_allowed_oauth_return_url(item)),BASE_URL)
 parts=urlsplit(target); query=[(k,v) for k,v in parse_qsl(parts.query,keep_blank_values=True) if k!='page']; query.append(('page','tools'))
 return urlunsplit((parts.scheme,parts.netloc,parts.path or '/',urlencode(query),parts.fragment))
@router.get('/api/mcp/servers')
def listing(request:Request): return api_success([out(x) for x in mcp_configs.list_for_user(uid(request))])
@router.get('/api/mcp/servers/{server_id}')
def detail(server_id:int,request:Request): return api_success(owned(request,server_id))
@router.post('/api/mcp/servers')
def create(payload:McpServerCreate,request:Request):
 user=uid(request); notion=payload.preset=='notion'
 name='Notion' if notion else payload.name; url=NOTION_URL if notion else payload.url; auth='oauth' if notion else payload.authType
 if not name or not url: raise HTTPException(422,'name and url are required')
 try: url=validate_remote_url(url)
 except Exception as e: raise HTTPException(400,str(e))
 headers=payload.headers or {}
 if auth=='headers':
  try: validate_static_headers(headers)
  except Exception as e: raise HTTPException(400,str(e))
 slug=re.sub(r'[^a-z0-9-]+','-',name.lower()).strip('-') or 'mcp'
 base=slug; n=2
 while any(x['slug']==slug for x in mcp_configs.list_for_user(user)): slug=f'{base}-{n}'; n+=1
 x=mcp_configs.create_server(user,name=name,slug=slug,url=url,auth_type=auth,enabled=payload.enabled)
 creds={};
 if headers: creds['headers']=headers
 if payload.clientId: creds['client_id']=payload.clientId
 if payload.clientSecret: creds['client_secret']=payload.clientSecret
 if creds: mcp_configs.save_credentials(user,x['id'],creds)
 if payload.enabledTools: mcp_configs.set_enabled_tools(user,x['id'],payload.enabledTools)
 return api_success(mcp_configs.get_owned(user,x['id']))
@router.patch('/api/mcp/servers/{server_id}')
def update(server_id:int,payload:McpServerUpdate,request:Request):
 user=uid(request); s=owned(request,server_id); supplied=payload.model_fields_set
 connection_fields={'url','authType','headers','clientId','clientSecret'}
 if s['slug']=='notion' and connection_fields & supplied: raise HTTPException(400,'Notion connection settings are fixed')
 next_url=s['url']; next_auth=s['authType']
 if 'url' in supplied:
  try: next_url=validate_remote_url(payload.url)
  except Exception as e: raise HTTPException(400,str(e))
 if 'authType' in supplied: next_auth=payload.authType
 headers=payload.headers if 'headers' in supplied else None
 if headers is not None:
  try: validate_static_headers(headers)
  except Exception as e: raise HTTPException(400,str(e))
 if 'headers' in supplied and next_auth!='headers': raise HTTPException(400,'Headers require headers authentication')
 if {'clientId','clientSecret'} & supplied and next_auth!='oauth': raise HTTPException(400,'OAuth credentials require OAuth authentication')
 url_changed=next_url!=s['url']; auth_changed=next_auth!=s['authType']; connection_changed=url_changed or auth_changed
 d=payload.model_dump(exclude_none=True); en=d.pop('enabledTools',None); d.pop('headers',None); d.pop('clientId',None); d.pop('clientSecret',None)
 if en is not None:
  names={t.get('name',t) if isinstance(t,dict) else t for t in (s.get('tools') or [])}
  vals=list(dict.fromkeys(en))
  if len(vals)>MCP_MAX_EXPOSED_TOOLS or any(x not in names for x in vals): raise HTTPException(400,'Invalid enabled tools')
 fields={k.replace('authType','auth_type'):v for k,v in d.items() if k in ('name','url','authType','enabled')}
 if connection_changed: fields['enabled']=False
 mcp_configs.update_server(user,server_id,**fields)
 cred_changed=bool({'headers','clientId','clientSecret'} & supplied) or connection_changed
 if cred_changed:
  old={} if connection_changed else ((mcp_configs.secret(user,server_id) or {}).get('credentials') or {})
  if 'headers' in supplied:
   if headers: old['headers']=headers
   else: old.pop('headers',None)
  if 'clientId' in supplied:
   if payload.clientId: old['client_id']=payload.clientId
   else: old.pop('client_id',None)
  if 'clientSecret' in supplied:
   if payload.clientSecret: old['client_secret']=payload.clientSecret
   else: old.pop('client_secret',None)
  mcp_configs.clear_credentials(user,server_id) if not old else mcp_configs.save_credentials(user,server_id,old)
 if connection_changed: mcp_configs.set_status(user,server_id,'disconnected')
 if en is not None: mcp_configs.set_enabled_tools(user,server_id,vals)
 return api_success(mcp_configs.get_owned(user,server_id))
@router.delete('/api/mcp/servers/{server_id}')
def delete(server_id:int,request:Request):
 user=uid(request); s=owned(request,server_id)
 if s['authType']=='oauth':
  try:mcp_oauth.revoke_credentials(user,server_id)
  except Exception: pass
 mcp_configs.clear_credentials(user,server_id); mcp_configs.delete_server(user,server_id); return api_success(True)
@router.post('/api/mcp/servers/{server_id}/disconnect')
def disconnect(server_id:int,request:Request):
 user=uid(request); s=owned(request,server_id)
 if s['authType']=='oauth':
  try:mcp_oauth.revoke_credentials(user,server_id)
  except Exception: pass
 mcp_configs.clear_credentials(user,server_id); mcp_configs.update_server(user,server_id,enabled=False); return api_success(mcp_configs.set_status(user,server_id,'disconnected'))
@router.post('/api/mcp/servers/{server_id}/test')
@router.post('/api/mcp/servers/{server_id}/refresh-tools')
def refresh(server_id:int,request:Request):
 user=uid(request); s=owned(request,server_id)
 try: tools=discover(user,s)
 except Exception: mcp_configs.set_status(user,server_id,'error',error_code='mcp_discovery_failed'); raise HTTPException(502,'MCP connection failed')
 mcp_configs.save_tool_snapshot(user,server_id,tools); return api_success(mcp_configs.set_status(user,server_id,'connected'))
@router.post('/api/mcp/servers/{server_id}/oauth/start')
def oauth_start(server_id:int,payload:McpOAuthStartIn,request:Request):
 user=uid(request); owned(request,server_id)
 if not is_allowed_oauth_return_url(payload.returnTo): raise HTTPException(400,'Invalid return URL')
 try:r=mcp_oauth.start_authorization(user,server_id,payload.returnTo)
 except Exception: raise HTTPException(502,'OAuth unavailable')
 return api_success({'authorizationUrl':r.get('authorizationUrl') or r.get('authorization_url')})
@router.get('/api/mcp/oauth/callback')
def oauth_callback(state:str,request:Request,code:str|None=None,error:str|None=None):
 user=get_current_user(request)
 if not user: raise HTTPException(401,'Please sign in first.')
 try:r=mcp_oauth.complete_authorization(int(user['id']),state,code,error)
 except McpOAuthError as exc:
  target=exc.return_to
  if not target or not is_allowed_oauth_return_url(target): target=oauth_default_return_url()
  return RedirectResponse(oauth_result_url(target,'mcpError',exc.code))
 except Exception: raise HTTPException(400,'Invalid OAuth state')
 target=(r.get('returnTo') or r.get('return_to') or BASE_URL) if isinstance(r,dict) else BASE_URL
 return RedirectResponse(oauth_result_url(target,'mcpResult','connected') if is_allowed_oauth_return_url(target) else BASE_URL)
