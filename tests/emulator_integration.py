"""Actual RTDB REST/ETag integration. Run with the local demo emulator only."""
import sys,threading,time,requests
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rtdb_store import RealtimeStore
from app import create_app
s=object.__new__(RealtimeStore);s.url='http://127.0.0.1:9000'
s.local=threading.local();s.local.http=requests.Session();s.local.http.trust_env=False
s.local.http.headers['Authorization']='Bearer owner'
original=s.local.http.request
def request(method,url,**kw):
 kw.setdefault('params',{})['ns']='demo-fleetrtdb-default-rtdb';return original(method,url,**kw)
s.local.http.request=request
app=create_app({'SECRET_KEY':'emulator-only-test-secret','STORE':s,'TESTING':True,'SESSION_COOKIE_SECURE':False})
r=app.test_cli_runner().invoke(args=['create-admin','--username','testadmin','--name','Admin','--password','long-password-123']);assert r.exit_code==0,r.output
client=app.test_client();client.get('/login')
with client.session_transaction() as session:csrf=session['csrf']
r=client.post('/login',data={'csrf':csrf,'username':'testadmin','password':'long-password-123'});assert r.status_code==302
with client.session_transaction() as session:csrf=session['csrf']
def api(path,body,method='POST'):
 r=client.open(path,method=method,json=body,headers={'X-CSRF-Token':csrf});assert r.status_code<300,(r.status_code,r.json);return r.json
u=api('/api/users',{'username':'driver','name':'Driver','password':'long-password-123'})
v=api('/api/vehicles',{'name':'Car','plate':'TEST','device_id':'TEST_DEVICE','owner_id':u['id'],'mac':'AA:BB:CC:DD:EE:FF'})
def upload():
 return client.post('/api/gps',headers={'Authorization':'Bearer '+v['token']},json={'device_id':'TEST_DEVICE','mac':'AA:BB:CC:DD:EE:FF','latitude':31,'longitude':74,'fix_time':int(time.time())})
r=upload();assert r.status_code==200,r.json
assert s.get('live/'+v['id'])['latitude']==31
assert s.query('vehicles/'+v['id']+'/points')
api('/api/vehicles/'+v['id']+'/fence',{'kind':'radius','lat':0,'lng':0,'km':1})
r=upload();assert r.json['command']['phase']=='return_warning',r.json
api('/api/users/'+u['id'],{'confirm':'driver'},method='DELETE')
assert upload().status_code==403
assert s.get('vehicles/'+v['id'])['deleted']
print('REAL RTDB REST: login, registration, upload, history, live projection, geofence and deletion passed.')
