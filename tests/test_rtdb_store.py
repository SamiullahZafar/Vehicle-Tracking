"""Transport-contract tests with an ETag-aware fake RTDB server."""
import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rtdb_store import RealtimeStore,StoreError,extract,assign

class Response:
 def __init__(self,data,tag='1',status=200):self.data=data;self.headers={'ETag':tag};self.status_code=status
 def json(self):return copy.deepcopy(self.data)
class FakeREST:
 def __init__(self):self.tree={};self.version=1;self.conflict=False;self.fail_history=False;self.calls=[]
 def __call__(self,method,path,**kw):
  self.calls.append((method,path,copy.deepcopy(kw)))
  if method=='GET':
   data=extract(self.tree,path) if path else copy.deepcopy(self.tree)
   params=kw.get('params',{})
   if params and isinstance(data,dict):
    import json
    order=json.loads(params.get('orderBy','"$key"'))
    rows=list(data.items());key=lambda item:item[0] if order=='$key' else item[1].get(order)
    rows.sort(key=key)
    if 'equalTo' in params:rows=[r for r in rows if key(r)==json.loads(params['equalTo'])]
    if 'startAt' in params:rows=[r for r in rows if key(r)>=json.loads(params['startAt'])]
    if 'endAt' in params:
     end=params['endAt'];end=json.loads(end) if isinstance(end,str) else end
     rows=[r for r in rows if key(r)<=end]
    if 'limitToFirst' in params:rows=rows[:params['limitToFirst']]
    if 'limitToLast' in params:rows=rows[-params['limitToLast']:]
    data=dict(rows)
   return Response(data,str(self.version))
  if method=='PUT':
   if self.conflict:
    self.conflict=False;self.version+=1
    assign(self.tree,'state/vehicles/v/blocked',True)
    return Response({},status=412)
   expected=kw.get('headers',{}).get('if-match')
   if expected and expected!=str(self.version):return Response({},status=412)
   assign(self.tree,path,kw['json']);self.version+=1;return Response(kw['json'])
  if method=='PATCH':
   if path=='history' and self.fail_history:raise StoreError('UNAVAILABLE','Injected write failure')
   for k,v in kw['json'].items():assign(self.tree,(path+'/' if path else '')+k,v)
   self.version+=1;return Response(kw['json'])
  raise AssertionError(method)
class StoreTests(unittest.TestCase):
 def setUp(self):
  self.rest=FakeREST();self.store=object.__new__(RealtimeStore);self.store.request=self.rest
  self.store.put('users/u',{'id':'u','role':'customer'})
  self.store.put('vehicles/v',{'id':'v','owner_id':'u','blocked':False,'token_hash':'secret'})
 def test_vehicle_transaction_does_not_download_history_or_entire_fleet(self):
  self.store.put('vehicles/v/points/1700000000',{'id':'1700000000','fix_time':1700000000})
  self.rest.calls=[]
  def update(tx):
   v=tx.get('vehicles/v');tx.put('vehicles/v',v|{'latitude':31});tx.put('live/v',{'latitude':31});return 1
  self.assertEqual(self.store.atomic(update,scope='vehicles/v'),1)
  self.assertEqual([p for m,p,k in self.rest.calls if m=='GET'],['state/vehicles/v'])
  self.assertEqual(self.store.get('live/v'),{'latitude':31})
  self.assertNotIn('public',self.store.get('vehicles/v'))
  self.assertIsNotNone(self.store.get('vehicles/v/points/1700000000'))
 def test_conflict_retries_without_losing_admin_block(self):
  self.rest.conflict=True
  def update(tx):
   v=tx.get('vehicles/v');tx.put('vehicles/v',v|{'latitude':31})
  self.store.atomic(update,scope='vehicles/v')
  self.assertTrue(self.store.get('vehicles/v')['blocked'])
 def test_history_failure_never_acknowledged_then_idempotent_retry(self):
  def update(tx):
   tx.put('vehicles/v',tx.get('vehicles/v'))
   tx.put('vehicles/v/points/1700000000',{'id':'1700000000','fix_time':1700000000})
   return 'accepted'
  self.rest.fail_history=True
  with self.assertRaises(StoreError):self.store.atomic(update,scope='vehicles/v')
  self.rest.fail_history=False
  for _ in range(2):self.assertEqual(self.store.atomic(update,scope='vehicles/v'),'accepted')
  self.assertEqual(len(self.store.query('vehicles/v/points')),1)
 def test_delete_customer_marks_all_vehicles_atomically(self):
  def update(tx):
   for v in tx.query_vehicles('u'):tx.put('vehicles/'+v['id'],{'id':v['id'],'owner_id':'u','deleted':True})
   tx.put('users/u',{'deleted':True})
  self.store.atomic(update)
  self.assertTrue(self.store.get('vehicles/v')['deleted'])
 def test_paged_history_has_no_repeat(self):
  for i in range(100,110):self.store.put(f'vehicles/v/points/{i:010d}',{'id':f'{i:010d}','fix_time':i})
  first=self.store.history_page('v',100,110,limit=5)
  second=self.store.history_page('v',100,110,[first[-1]['fix_time'],first[-1]['id']],limit=5)
  self.assertEqual([p['fix_time'] for p in first+second],list(range(100,110)))
 def test_device_indexes_and_queries(self):
  self.assertEqual(len(self.store.query('vehicles',where=('owner_id','u'))),1)
  self.assertEqual(self.store.query('vehicles',where=('owner_id','other')),[])
 def test_login_throttle(self):
  for _ in range(15):self.assertTrue(self.store.allow_login('hash'))
  self.assertFalse(self.store.allow_login('hash'))
 def test_delete_parent_and_live_path_not_overlapping(self):
  self.store.delete_many(['vehicles/v','live/v'])
  self.assertIsNone(self.store.get('vehicles/v'))
if __name__=='__main__':unittest.main()
