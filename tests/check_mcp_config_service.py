import json, sqlite3, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from cryptography.fernet import Fernet
from knowflow.services.mcp_config import McpConfigService

class C:
 def __init__(self): self.f=Fernet(Fernet.generate_key())
 def encrypt(self,v): return self.f.encrypt(v.encode()).decode()
 def decrypt(self,v):
  try:return self.f.decrypt((v or '').encode()).decode()
  except:return ''
class ThrowingCipher:
 def decrypt(self,v): raise RuntimeError('boom')

db=sqlite3.connect(':memory:'); db.row_factory=sqlite3.Row
db.executescript('''create table mcp_server(id integer primary key,user_id int,name,slug,url,auth_type,enabled int,status,credentials_cipher,tools_json,enabled_tools_json,last_error_code,last_connected_at,created_at,updated_at); create table mcp_oauth_session(id text primary key,user_id int,server_id int,state_hash,pkce_verifier_cipher,return_to,expires_at,created_at);''')
def all_(sql,p=None): return [dict(x) for x in db.execute(sql,p or {}).fetchall()]
def one(sql,p=None):
 x=db.execute(sql,p or {}).fetchone(); return dict(x) if x else None
def exe(sql,p=None):
 c=db.execute(sql,p or {}); db.commit(); return c.lastrowid
def rc(sql,p=None):
 c=db.execute(sql,p or {}); db.commit(); return c.rowcount
s=McpConfigService(fetch_one=one,fetch_all=all_,execute=exe,execute_rowcount=rc,cipher=C(),now_str=lambda:'2026-01-01 00:00:00')
svc_throw=McpConfigService(fetch_one=one,fetch_all=all_,execute=exe,execute_rowcount=rc,cipher=ThrowingCipher(),now_str=lambda:'2026-01-01 00:00:00')
assert svc_throw.decrypt_credentials('x') == {}
assert svc_throw.normalize({'id':1,'user_id':1,'name':'n','slug':'s','url':'u','auth_type':'none','credentials_cipher':'x'})['configured'] is False
a=s.create_server(1,name='Notion',slug='notion',url='u',auth_type='oauth'); b=s.create_server(2,name='Notion',slug='notion',url='u',auth_type='oauth')
assert a['id']!=b['id'] and s.get_owned(1,b['id']) is None
assert [item['id'] for item in s.list_for_user(1)] == [a['id']]
s.update_server(1, a['id'], name='Updated', enabled=False)
assert s.get_owned(1, a['id'])['name'] == 'Updated' and not s.get_owned(1, a['id'])['enabled']
s.set_status(1, a['id'], 'error', error_code='E_TEST')
assert s.get_owned(1, a['id'])['status'] == 'error' and s.get_owned(1, a['id'])['lastErrorCode'] == 'E_TEST'
s.save_credentials(1,a['id'],{'access_token':'unit-access','refresh_token':'unit-refresh'})
raw=one('select credentials_cipher from mcp_server where id=1'); assert 'unit-access' not in raw['credentials_cipher']; assert s.get_owned(1,a['id'])['configured']; secret=s.secret(1,a['id']); assert 'credentials_cipher' not in secret and secret['credentials']['access_token']=='unit-access'
s.save_tool_snapshot(1,a['id'],[{'name':'a'},{'name':'b'}]); assert s.get_owned(1,a['id'])['enabledTools']==['a','b']
s.save_tool_snapshot(1,a['id'],[{'name':'b'},{'name':'c'}]); assert s.get_owned(1,a['id'])['enabledTools']==['b']
many=[{'name':f'tool-{i}'} for i in range(33)]
s.save_tool_snapshot(2,b['id'],many); assert s.get_owned(2,b['id'])['enabledTools']==[]
sid=s.create_oauth_session(1,a['id'],state_hash='h',pkce_verifier_cipher='p',return_to='/',expires_at='2099-01-01')['id']; assert s.consume_oauth_session(1,sid,'h'); assert s.consume_oauth_session(1,sid,'h') is None
try: s.create_oauth_session(2,a['id'],state_hash='cross',pkce_verifier_cipher='p',return_to='/',expires_at='2099-01-01'); raise AssertionError('cross-user session accepted')
except ValueError: pass
s.create_oauth_session(1,a['id'],state_hash='expired-a',pkce_verifier_cipher='p',return_to='/',expires_at='2020-01-01')
s.create_oauth_session(2,b['id'],state_hash='expired-b',pkce_verifier_cipher='p',return_to='/',expires_at='2020-01-01')
s.create_oauth_session(1,a['id'],state_hash='live-a',pkce_verifier_cipher='p',return_to='/',expires_at='2099-01-01')
s.create_oauth_session(1,a['id'],state_hash='equal-a',pkce_verifier_cipher='p',return_to='/',expires_at='2026-01-01 00:00:00')
assert s.delete_expired_oauth_sessions(1, now='2026-01-01 00:00:00') == 2
assert one('select id from mcp_oauth_session where state_hash="expired-b"') is not None
assert one('select id from mcp_oauth_session where state_hash="live-a"') is not None
assert one('select id from mcp_oauth_session where state_hash="equal-a"') is None
s.delete_server(1,a['id']); assert s.get_owned(1,a['id']) is None
print('mcp config checks passed')
