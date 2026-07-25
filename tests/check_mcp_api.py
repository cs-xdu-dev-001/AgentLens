import importlib, os, sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]; DB=ROOT/'data'/'test-dbs'/'mcp-api.db'
def main():
    DB.unlink(missing_ok=True)
    os.environ.update(KNOWFLOW_DB_URL=f'sqlite:///{DB.as_posix()}', KNOWFLOW_SECRET_KEY='mcp-test-secret', KNOWFLOW_BASE_URL='http://127.0.0.1:8010', KNOWFLOW_OAUTH_RETURN_ORIGINS='http://127.0.0.1:5173', KNOWFLOW_VECTOR_STORE='local')
    os.environ["KNOWFLOW_COOKIE_SECURE"] = "0"
    sys.path.insert(0,str(ROOT/'backend'))
    for n in list(sys.modules):
        if n=='main' or n.startswith('knowflow'): sys.modules.pop(n,None)
    app=importlib.import_module('main').app; c=TestClient(app); bob=TestClient(app)
    for cli,u in ((c,'alice'),(bob,'bob')):
        r=cli.post('/api/auth/register',json={'username':u,'email':u+'@example.com','password':'123456','displayName':u}); assert r.status_code==200,r.text
    notion=c.post('/api/mcp/servers',json={'preset':'notion'}); assert notion.status_code in (200,201),notion.text
    assert notion.json()['data']['url']=='https://mcp.notion.com/mcp' and notion.json()['data']['name']=='Notion'
    notion_id=notion.json()['data']['id']
    assert c.patch(f'/api/mcp/servers/{notion_id}',json={'url':'https://example.com/mcp'}).status_code==400
    created=c.post('/api/mcp/servers',json={'name':'Private','url':'https://example.com/mcp','authType':'headers','headers':{'Authorization':'Bearer SECRET'}}); assert created.status_code in (200,201),created.text
    sid=created.json()['data']['id']; raw=str(created.json()); assert 'SECRET' not in raw and 'credentials_cipher' not in raw.lower()
    assert c.patch(f'/api/mcp/servers/{sid}',json={'headers':{}}).status_code==200
    assert not (router_secret:=importlib.import_module('knowflow.routers.mcp').mcp_configs.secret(1,sid) or {}).get('credentials')
    assert c.patch(f'/api/mcp/servers/{sid}',json={'url':'http://127.0.0.1:9000/mcp'}).status_code==400
    edited=c.patch(f'/api/mcp/servers/{sid}',json={'url':'https://example.org/mcp','authType':'none'})
    assert edited.status_code==200 and edited.json()['data']['url']=='https://example.org/mcp' and edited.json()['data']['authType']=='none'
    assert edited.json()['data']['enabled'] is False and edited.json()['data']['configured'] is False
    assert bob.get(f'/api/mcp/servers/{sid}').status_code==404
    assert bob.patch(f'/api/mcp/servers/{sid}',json={'enabled':False}).status_code==404
    assert bob.post(f'/api/mcp/servers/{sid}/test').status_code==404
    assert bob.post(f'/api/mcp/servers/{sid}/refresh-tools').status_code==404
    assert bob.post(f'/api/mcp/servers/{sid}/disconnect').status_code==404
    assert bob.post(f'/api/mcp/servers/{sid}/oauth/start',json={'returnTo':'http://127.0.0.1:5173/'}).status_code==404
    assert bob.delete(f'/api/mcp/servers/{sid}').status_code==404
    router=importlib.import_module('knowflow.routers.mcp'); router.discover=lambda user,s:[{'name':'read','description':'x'},{'name':'write'}]
    ok=c.post(f'/api/mcp/servers/{sid}/refresh-tools'); assert ok.status_code==200,ok.text
    assert c.patch(f'/api/mcp/servers/{sid}',json={'enabledTools':['read']}).status_code==200
    before=c.get(f'/api/mcp/servers/{sid}').json()['data']
    atomic=c.patch(f'/api/mcp/servers/{sid}',json={'url':'https://example.com/changed','enabledTools':['missing']})
    assert atomic.status_code==400
    after=c.get(f'/api/mcp/servers/{sid}').json()['data']
    assert after['url']==before['url'] and after['enabled']==before['enabled'] and after['status']==before['status']
    assert c.patch(f'/api/mcp/servers/{sid}',json={'enabledTools':['missing']}).status_code==400
    assert c.patch(f'/api/mcp/servers/{sid}',json={'enabledTools':['t'+str(i) for i in range(65)]}).status_code==400
    router.discover=lambda user,s: (_ for _ in ()).throw(RuntimeError())
    bad=c.post(f'/api/mcp/servers/{sid}/refresh-tools'); assert bad.status_code==502
    assert c.get(f'/api/mcp/servers/{sid}').json()['data']['status']=='error'
    assert c.post('/api/mcp/servers/999999/oauth/start',json={'returnTo':'http://127.0.0.1:5173/'}).status_code==404
    assert TestClient(app).get('/api/mcp/oauth/callback?state=x').status_code==401
    assert c.post(f'/api/mcp/servers/{sid}/oauth/start',json={'returnTo':'https://evil.example/'}).status_code==400
    assert c.delete(f'/api/mcp/servers/{sid}').status_code==200

    oauth=c.post('/api/mcp/servers',json={'name':'OAuth','url':'https://example.com/oauth','authType':'oauth'}); oid=oauth.json()['data']['id']
    router.mcp_oauth.start_authorization=lambda *a: {'authorizationUrl':'https://idp.example/auth'}
    assert c.post(f'/api/mcp/servers/{oid}/oauth/start',json={'returnTo':'http://127.0.0.1:5173/'}).json()['data']['authorizationUrl']=='https://idp.example/auth'
    dis=c.post(f'/api/mcp/servers/{oid}/disconnect'); assert dis.status_code==200 and dis.json()['data']['enabled'] is False and dis.json()['data']['configured'] is False and dis.json()['data']['status']=='disconnected'
    cb=c.get('/api/mcp/oauth/callback?state=bad',follow_redirects=False); assert cb.status_code==307
    target=urlsplit(cb.headers['location']); assert target.path=='/'
    assert parse_qs(target.query)=={'page':['tools'],'mcpError':['invalid_state']}
    router.mcp_oauth.complete_authorization=lambda *a: {'returnTo':'http://127.0.0.1:5173/ok?from=test#tools'}
    cb=c.get('/api/mcp/oauth/callback?state=ok',follow_redirects=False); assert cb.status_code==307
    target=urlsplit(cb.headers['location']); assert target.path=='/ok' and target.fragment=='tools'
    assert parse_qs(target.query)=={'from':['test'],'mcpResult':['connected']}
    oauth_error=importlib.import_module('knowflow.services.mcp_oauth').McpOAuthError
    router.mcp_oauth.complete_authorization=lambda *a: (_ for _ in ()).throw(oauth_error('authorization_denied',return_to='http://127.0.0.1:5173/ok?from=test#tools'))
    cb=c.get('/api/mcp/oauth/callback?state=denied',follow_redirects=False); assert cb.status_code==307
    target=urlsplit(cb.headers['location']); assert target.fragment=='tools'
    assert parse_qs(target.query)=={'from':['test'],'mcpError':['authorization_denied']}
    router.mcp_oauth.complete_authorization=lambda *a: {'returnTo':'https://evil.example/'}
    cb=c.get('/api/mcp/oauth/callback?state=ok',follow_redirects=False); assert cb.headers['location']=='http://127.0.0.1:8010'
    router.mcp_oauth.revoke_credentials=lambda *a: (_ for _ in ()).throw(RuntimeError())
    assert c.delete(f'/api/mcp/servers/{oid}').status_code==200 and c.get(f'/api/mcp/servers/{oid}').status_code==404
    print('ok: MCP API TestClient coverage')
if __name__=='__main__': main()
