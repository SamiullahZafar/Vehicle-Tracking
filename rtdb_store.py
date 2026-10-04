"""Firebase RTDB REST transport; requests honors PythonAnywhere's HTTPS proxy.

Metadata/live state use optimistic ETag transactions. History is separately
acknowledged, idempotent data: a failed history write never acknowledges a device
batch. No history tree is downloaded by an upload transaction.
"""
import copy, json, re, threading, time, random
from urllib.parse import urlparse, quote
from google.oauth2 import service_account
from google.auth.transport.requests import AuthorizedSession
from google.auth.exceptions import GoogleAuthError
from requests.exceptions import RequestException

class StoreError(Exception):
    def __init__(self,status,message):
        self.status=status
        super().__init__(message)

def path_for(path):
    parts=path.split('/')
    if parts[0]=='live':return 'state/vehicles/'+parts[1]+'/public'
    if parts[0]=='vehicles' and len(parts)>=3:
        return 'history/'+'/'.join(parts[1:])
    return 'state/'+path

def extract(tree,path):
    for key in path.split('/') if path else []:
        if not isinstance(tree,dict):return None
        tree=tree.get(key)
    return copy.deepcopy(tree)

def assign(tree,path,value):
    keys=path.split('/')
    for key in keys[:-1]:tree=tree.setdefault(key,{})
    if value is None:tree.pop(keys[-1],None)
    else:tree[keys[-1]]=copy.deepcopy(value)

def clean(value):
    if isinstance(value,dict):value=copy.deepcopy(value);value.pop('public',None)
    return value

class RealtimeStore:
    def __init__(self,project,keyfile,url):
        parsed=urlparse(url)
        if parsed.scheme!='https' or not parsed.hostname or not parsed.hostname.endswith(('.firebaseio.com','.firebasedatabase.app')) or parsed.path not in ('','/') or parsed.query:
            raise ValueError('FIREBASE_DATABASE_URL must be the exact HTTPS Realtime Database URL')
        self.url=url.rstrip('/')
        self.credentials=service_account.Credentials.from_service_account_file(keyfile,scopes=[
            'https://www.googleapis.com/auth/firebase.database','https://www.googleapis.com/auth/userinfo.email'])
        if self.credentials.project_id!=project:raise ValueError('Service account and FIREBASE_PROJECT_ID differ')
        self.local=threading.local()

    def request(self,method,path,**kwargs):
        if not hasattr(self.local,'http'):self.local.http=AuthorizedSession(self.credentials)
        try:r=self.local.http.request(method,self.url+'/'+quote(path,safe='/')+'.json',timeout=(5,15),**kwargs)
        except (RequestException,GoogleAuthError) as e:raise StoreError('UNAVAILABLE','Database connection or service-account authentication failed') from e
        if r.status_code==412:return r
        if not r.ok:raise StoreError(str(r.status_code),'RTDB rejected request; check URL, service-account permissions, indexes and outbound network')
        return r

    def get(self,path):return clean(self.request('GET',path_for(path)).json())
    def allow_login(self,key):
        now=time.time()
        for _ in range(6):
            r=self.request('GET','limits/'+key,headers={'X-Firebase-ETag':'true'})
            d=r.json() or {}
            if now-d.get('at',0)>900:d={'at':now,'count':0}
            if d.get('count',0)>=15:return False
            d['count']=d.get('count',0)+1
            w=self.request('PUT','limits/'+key,json=d,headers={'if-match':r.headers['ETag']})
            if w.status_code!=412:return True
        raise StoreError('CONFLICT','Login busy; retry shortly')
    def put(self,path,value):self.request('PUT',path_for(path),json=value)
    def delete_many(self,paths):
        # Drop child paths covered by a parent to avoid overlapping PATCH keys.
        keys=sorted(set(path_for(p) for p in paths),key=len)
        selected=[]
        for key in keys:
            if not any(key.startswith(p+'/') for p in selected):selected.append(key)
        if selected:self.request('PATCH','',json={p:None for p in selected})

    def query(self,collection,where=None,order=None,limit=2000):
        params={}
        if where:params={'orderBy':json.dumps(where[0]),'equalTo':json.dumps(where[1]),'limitToFirst':limit}
        elif order:params={'orderBy':json.dumps(order),'limitToLast':limit}
        else:params={'orderBy':json.dumps('$key'),'limitToFirst':limit}
        data=self.request('GET',path_for(collection),params=params).json() or {}
        rows=[clean(x) for x in data.values()]
        if order:rows.sort(key=lambda x:x.get(order,0),reverse=True)
        return rows

    def history_page(self,vid,start,end,cursor=None,limit=500):
        # Keys sort by UTC second; one sample per second matches NEO-6M output.
        low=f'{int(start):010d}' if not cursor else f'{int(cursor[0])+1:010d}'
        high=f'{int(end)-1:010d}'
        if low>high:return []
        data=self.request('GET',f'history/{vid}/points',params={'orderBy':'"$key"','startAt':json.dumps(low),'endAt':json.dumps(high),'limitToFirst':limit}).json() or {}
        return [data[k] for k in sorted(data)]

    def older_history(self,vid,kind,field,cutoff,limit):
        data=self.request('GET',f'history/{vid}/{kind}',params={'orderBy':json.dumps(field),'endAt':cutoff,'limitToFirst':limit}).json() or {}
        return list(data.values())

    def prune_login_limits(self):
        while True:
            old=self.request('GET','limits',params={'orderBy':'"at"','endAt':time.time()-86400,'limitToFirst':200}).json() or {}
            if not old:return
            self.request('PATCH','limits',json={key:None for key in old})

    def custom_token(self,uid,version=0):
        from google.auth import jwt
        now=int(time.time())
        return jwt.encode(self.credentials.signer,{'iss':self.credentials.service_account_email,
            'sub':self.credentials.service_account_email,'aud':'https://identitytoolkit.googleapis.com/google.identity.identitytoolkit.v1.IdentityToolkit',
            'iat':now,'exp':now+3600,'uid':uid,'claims':{'sv':version}}).decode()

    def atomic(self,fn,scope=None):
        root=path_for(scope) if scope else 'state'
        for attempt in range(6):
            response=self.request('GET',root,headers={'X-Firebase-ETag':'true'})
            snapshot=response.json() or {}
            tx=Transaction(self,root,snapshot)
            result=fn(tx)
            response=self.request('PUT',root,json=tx.snapshot,headers={'if-match':response.headers['ETag']})
            if response.status_code==412:
                time.sleep(random.uniform(.01,.05)*(attempt+1));continue
            if tx.history:self.request('PATCH','history',json=tx.history)
            return result
        raise StoreError('CONFLICT','Concurrent update; retry the request')

class Transaction:
    def __init__(self,store,root,snapshot):self.store=store;self.root=root;self.snapshot=snapshot;self.history={}
    def get(self,path):
        target=path_for(path)
        if target==self.root:return clean(self.snapshot)
        if target.startswith(self.root+'/'):return clean(extract(self.snapshot,target[len(self.root)+1:]))
        return self.store.get(path)
    def query_vehicles(self,owner):
        if self.root!='state':raise RuntimeError('Owner deletion needs metadata transaction')
        return [clean(v) for v in self.snapshot.get('vehicles',{}).values() if v.get('owner_id')==owner]
    def put(self,path,value):
        target=path_for(path)
        if target.startswith('history/'):
            self.history[target[8:]]=copy.deepcopy(value);return
        if target==self.root:self.snapshot=copy.deepcopy(value)
        elif target.startswith(self.root+'/'):assign(self.snapshot,target[len(self.root)+1:],value)
        else:raise RuntimeError('Transaction write outside its scope')
