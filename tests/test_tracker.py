import unittest,copy,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import create_app,ident
from rtdb_store import StoreError
from werkzeug.security import generate_password_hash

class MemoryStore:
 def __init__(self):self.docs={}
 def get(self,p):return copy.deepcopy(self.docs.get(p))
 def put(self,p,d):self.docs[p]=copy.deepcopy(d)
 def delete_many(self,paths):
  for p in paths:self.docs.pop(p,None)
 def query(self,c,where=None,order=None,limit=2000):
  rows=[copy.deepcopy(v) for p,v in self.docs.items() if p.startswith(c+'/') and len(p.split('/'))==len(c.split('/'))+1]
  if where:rows=[v for v in rows if v.get(where[0])==where[1]]
  if order:rows.sort(key=lambda d:d[order],reverse=True)
  return rows[:limit]
 def allow_login(self,key):return True
 def query_vehicles(self,owner):return self.query("vehicles",where=("owner_id",owner))
 def atomic(self,fn,scope=None):
  old=copy.deepcopy(self.docs)
  try:return fn(self)
  except Exception:self.docs=old;raise

class TrackerTests(unittest.TestCase):
 def setUp(self):
  self.store=MemoryStore();self.app=create_app({'TESTING':True,'SECRET_KEY':'test','STORE':self.store,'SESSION_COOKIE_SECURE':False})
  self.c=self.app.test_client();self.admin='a'*32;self.alice='b'*32;self.bob='c'*32;self.va='d'*32;self.vb='e'*32
  for uid,name,role in [(self.admin,'admin','admin'),(self.alice,'alice','customer'),(self.bob,'bob','customer')]:
   self.store.put('users/'+uid,dict(id=uid,name=name,username=name,role=role,active=True,deleted=False,password=generate_password_hash('long-password')))
   self.store.put('usernames/'+ident(name),{'uid':uid})
  for vid,owner,dev in [(self.va,self.alice,'A'),(self.vb,self.bob,'B')]:
   self.store.put('vehicles/'+vid,dict(id=vid,owner_id=owner,device_id=dev,name=dev,plate=dev,token_hash=ident('test-token'),deleted=False))
   self.store.put('devices/'+ident(dev),{'vid':vid})
 def login(self,uid):
  with self.c.session_transaction() as s:s.update(uid=uid,csrf='csrf')
 def call(self,path,method='POST',data=None):return self.c.open(path,method=method,json=data,headers={'X-CSRF-Token':'csrf','Authorization':'Bearer test-token'})
 def upload(self,dev):return self.call('/api/gps',data={'device_id':dev,'latitude':0,'longitude':74.2,'speed':0,'fix_time':time.time()})
 def test_customer_scope(self):
  self.login(self.alice)
  self.assertEqual(len(self.c.get('/api/vehicles').json),1)
  self.assertEqual(self.c.get('/api/vehicles/'+self.vb+'/history').status_code,404)
  for path,confirm in [('/api/vehicles/'+self.va,'A'),('/api/users/'+self.bob,'bob')]:self.assertEqual(self.call(path,'DELETE',{'confirm':confirm}).status_code,403)
 def test_csrf_confirm_and_admin(self):
  self.login(self.admin)
  self.assertEqual(self.c.delete('/api/vehicles/'+self.va,json={'confirm':'A'}).status_code,400)
  self.assertEqual(self.call('/api/vehicles/'+self.va,'DELETE',{'confirm':'bad'}).status_code,400)
  self.assertEqual(self.call('/api/users/'+self.admin,'DELETE',{'confirm':'admin'}).status_code,403)
  self.assertFalse(self.store.get('vehicles/'+self.va)['deleted'])
 def test_delete_owner_immediately_blocks_child_uploads_and_session(self):
  self.upload('A');self.login(self.admin)
  r=self.call('/api/users/'+self.alice,'DELETE',{'confirm':'alice'})
  self.assertEqual(r.status_code,200);self.assertTrue(r.json['cleanup_pending'])
  self.assertEqual(self.upload('A').status_code,403)
  self.assertEqual(len(self.c.get('/api/vehicles').json),1)
  self.login(self.alice);self.assertEqual(self.c.get('/api/vehicles').status_code,401)
  self.assertEqual(self.upload('B').status_code,200)
 def test_cleanup_pages_and_reservations(self):
  for i in range(405):self.store.put('vehicles/'+self.va+'/points/'+str(i),{'id':str(i),'received':i})
  self.login(self.admin);self.call('/api/vehicles/'+self.va,'DELETE',{'confirm':'A'})
  
  for j in self.store.docs.values():
   if j.get('status')=='pending':j['at']-=1201
  runner=self.app.test_cli_runner();r=runner.invoke(args=['purge-deleted']);self.assertEqual(r.exit_code,0,r.output)
  self.assertFalse(any(p.startswith('vehicles/'+self.va) for p in self.store.docs))
  self.assertIsNotNone(self.store.get('devices/'+ident('A')))
  self.assertEqual(self.upload('A').status_code,403)
  self.assertEqual(runner.invoke(args=['purge-deleted']).exit_code,0)
 def test_cleanup_failure_can_resume(self):
  self.upload('A');self.login(self.admin);self.call('/api/users/'+self.alice,'DELETE',{'confirm':'alice'})
  for j in self.store.docs.values():
   if j.get('status')=='pending':j['at']-=1201
  original=self.store.delete_many
  def fail(paths):raise StoreError('UNAVAILABLE','test')
  self.store.delete_many=fail
  self.assertNotEqual(self.app.test_cli_runner().invoke(args=['purge-deleted']).exit_code,0)
  self.assertEqual(self.upload('A').status_code,403)
  self.store.delete_many=original
  self.assertEqual(self.app.test_cli_runner().invoke(args=['purge-deleted']).exit_code,0)
  self.assertIsNone(self.store.get('users/'+self.alice))
 def test_login_and_suspend(self):
  self.c.get('/login')
  with self.c.session_transaction() as s:csrf=s['csrf']
  self.assertEqual(self.c.post('/login',data={'csrf':csrf,'username':'alice','password':'long-password'}).status_code,302)
  self.assertEqual(self.c.get('/').status_code,200)
  self.login(self.admin);self.call('/api/users/'+self.alice+'/active',data={'active':False});self.login(self.alice)
  self.assertEqual(self.c.get('/api/vehicles').status_code,401)
 def test_register_duplicates_and_token(self):
  self.login(self.admin);b=dict(name='C',plate='C',device_id='C',owner_id=self.alice,legacy=False)
  r=self.call('/api/vehicles',data=b);self.assertEqual(r.status_code,201)
  self.assertEqual(self.call('/api/vehicles',data=b).status_code,409)
  self.assertEqual(self.upload('C').status_code,401)
  r2=self.c.post('/api/gps',json={'device_id':'C','latitude':1,'longitude':2},headers={'Authorization':'Bearer '+r.json['token']})
  self.assertEqual(r2.status_code,200)
 def test_history_validation_and_deleted_owner_registration(self):
  self.upload('A');self.login(self.alice)
  self.assertEqual(len(self.c.get('/api/vehicles/'+self.va+'/history').json),1)
  self.assertEqual(self.call('/api/gps',data={'device_id':'A','latitude':999,'longitude':1}).status_code,400)
  self.login(self.admin);self.call('/api/users/'+self.alice,'DELETE',{'confirm':'alice'})
  self.assertEqual(self.call('/api/vehicles',data=dict(name='D',plate='D',device_id='D',owner_id=self.alice)).status_code,400)

class RestrictionTests(unittest.TestCase):
 setUp=TrackerTests.setUp
 login=TrackerTests.login
 call=TrackerTests.call
 upload=TrackerTests.upload
 def test_customer_cannot_control_admin_block(self):
  self.login(self.alice)
  self.assertEqual(self.call('/api/vehicles/'+self.va+'/controls',data={'blocked':True}).status_code,403)
 def test_fence_ownership_lock_and_validation(self):
  self.login(self.alice);f={'kind':'radius','lat':31,'lng':74,'km':2}
  self.assertEqual(self.call('/api/vehicles/'+self.vb+'/fence',data=f).status_code,403)
  self.assertEqual(self.call('/api/vehicles/'+self.va+'/fence',data=f).status_code,200)
  self.login(self.admin);self.call('/api/vehicles/'+self.va+'/controls',data={'fence_locked':True})
  self.login(self.alice);self.assertEqual(self.call('/api/vehicles/'+self.va+'/fence',data=f).status_code,403)
  self.login(self.admin);self.assertEqual(self.call('/api/vehicles/'+self.va+'/fence',data=f|{'km':-1}).status_code,400)
  self.assertEqual(self.call('/api/vehicles/'+self.va+'/fence',data=f).status_code,200)
 def test_offline_samples_deduplicate_and_do_not_drive_fence(self):
  self.login(self.admin);self.call('/api/vehicles/'+self.va+'/fence',data={'kind':'radius','lat':31,'lng':74,'km':1})
  p={'latitude':0,'longitude':0,'fix_time':time.time()-1000}
  for _ in range(2):
   r=self.call('/api/gps',data={'device_id':'A','gps_valid':False,'samples':[p]})
   self.assertEqual(r.status_code,200);self.assertEqual(r.json['command']['phase'],'gps_unavailable')
  self.assertEqual(len(self.store.query('vehicles/'+self.va+'/points')),1)
 def test_manual_command_and_live_projection_no_secrets(self):
  self.login(self.admin);self.call('/api/vehicles/'+self.va+'/controls',data={'blocked':True})
  r=self.upload('A');self.assertEqual(r.json['command']['phase'],'manual_warning');self.assertEqual(r.json['engine_cutoff'],0)
  live=self.store.get('live/'+self.va)
  self.assertNotIn('token_hash',live);self.assertNotIn('password',live)
 def test_mac_check(self):
  self.login(self.admin);self.assertEqual(self.call('/api/vehicles/'+self.va+'/controls',data={'mac':'AA:BB:CC:DD:EE:FF'}).status_code,200)
  self.assertEqual(self.upload('A').status_code,403)
 def test_city_import_validation(self):
  g={'type':'Polygon','coordinates':[[[0,0],[1,0],[1,1],[0,0]]]}
  self.login(self.alice);self.assertEqual(self.call('/api/cities',data={'name':'Test','geometry':g}).status_code,403)
  self.login(self.admin);r=self.call('/api/cities',data={'name':'Test','geometry':g});self.assertEqual(r.status_code,200)
  self.login(self.alice);self.assertEqual(self.call('/api/vehicles/'+self.va+'/fence',data={'kind':'city','city_id':r.json['id']}).status_code,200)
 def test_live_doc_cleanup(self):
  self.upload('A');self.login(self.admin);self.call('/api/vehicles/'+self.va,'DELETE',{'confirm':'A'})
  self.assertTrue(self.store.get('live/'+self.va)['deleted'])
  for j in self.store.docs.values():
   if j.get('status')=='pending':j['at']-=1201
  r=self.app.test_cli_runner().invoke(args=['purge-deleted']);self.assertEqual(r.exit_code,0,r.output)
  self.assertIsNone(self.store.get('live/'+self.va))

class AdditionalControlTests(unittest.TestCase):
 setUp=TrackerTests.setUp
 login=TrackerTests.login
 call=TrackerTests.call
 upload=TrackerTests.upload
 def test_disabled_upload_rejected_then_restore(self):
  self.login(self.admin)
  self.assertEqual(self.call('/api/vehicles/'+self.va+'/controls',data={'uploads_enabled':False}).status_code,200)
  self.assertEqual(self.upload('A').status_code,403)
  self.call('/api/vehicles/'+self.va+'/controls',data={'uploads_enabled':True})
  self.assertEqual(self.upload('A').status_code,200)
 def test_token_rotation_revokes_old_token(self):
  self.login(self.admin)
  r=self.call('/api/vehicles/'+self.va+'/controls',data={'rotate_token':True})
  self.assertEqual(self.upload('A').status_code,401)
  r=self.c.post('/api/gps',json={'device_id':'A','gps_valid':False},headers={'Authorization':'Bearer '+r.json['token']})
  self.assertEqual(r.status_code,200)
 def test_password_change_checks_old_password_and_revokes_version(self):
  self.login(self.alice)
  self.assertEqual(self.call('/api/password',data={'current':'wrong','password':'new-long-password'}).status_code,403)
  self.assertEqual(self.call('/api/password',data={'current':'long-password','password':'new-long-password'}).status_code,200)
  self.assertEqual(self.store.get('users/'+self.alice)['session_version'],1)
 def test_cleanup_waits_for_inflight_uploads(self):
  self.login(self.admin);self.call('/api/vehicles/'+self.va,'DELETE',{'confirm':'A'})
  r=self.app.test_cli_runner().invoke(args=['purge-deleted'])
  self.assertEqual(r.exit_code,0);self.assertIn('Waiting',r.output)
  self.assertTrue(self.store.get('vehicles/'+self.va)['deleted'])

class DomainTests(unittest.TestCase):
 def test_radius_and_two_stage_warning_cancel(self):
  from domain import command
  v={'fence':{'kind':'radius','lat':31,'lng':74,'km':1}}
  state,c=command(v,1000,True,32,74);self.assertEqual(c['voice_track'],1)
  v['control']=state
  state,c=command(v,1060,True,32,74);self.assertEqual(c['voice_track'],2)
  state,c=command(v,1120,True,32,74);self.assertEqual(c['stop_request'],1);self.assertEqual(c['engine_cutoff'],0)
  state,c=command(v,1121,True,31,74);self.assertEqual(c['stop_request'],0);self.assertNotIn('breach_started',state)
 def test_manual_clock_starts_on_contact(self):
  from domain import command
  v={'blocked':True};state,c=command(v,1000,False);self.assertEqual(c['seconds_remaining'],600)
  v['control']=state
  _,c=command(v,1599,False);self.assertEqual(c['restart_inhibit_requested'],0)
  _,c=command(v,1600,False);self.assertEqual(c['restart_inhibit_requested'],1)
 def test_stale_gps_resets_boundary_warning(self):
  from domain import command
  s,c=command({'control':{'breach_started':1}},999,False)
  self.assertEqual(c['phase'],'gps_unavailable');self.assertNotIn('breach_started',s)
 def test_polygon_holes_and_multicity(self):
  from domain import inside,geometry
  outer=[[0,0],[10,0],[10,10],[0,10],[0,0]];hole=[[3,3],[5,3],[5,5],[3,5],[3,3]]
  f={'kind':'city','geometry':geometry({'type':'MultiPolygon','coordinates':[[outer,hole]]})}
  self.assertTrue(inside(f,1,1));self.assertFalse(inside(f,4,4));self.assertFalse(inside(f,20,20))


