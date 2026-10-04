from flask import Flask,render_template,request,jsonify,session,g,abort,redirect
from werkzeug.security import generate_password_hash,check_password_hash
from functools import wraps
from pathlib import Path
from dotenv import load_dotenv
from rtdb_store import RealtimeStore,StoreError
import os,secrets,hashlib,math,time,uuid,click,json,re
from datetime import datetime,timezone,timedelta
from domain import command,geometry,number

BASE=Path(__file__).resolve().parent
load_dotenv(BASE/'.env')
def ident(s):return hashlib.sha256(s.encode()).hexdigest()
def new_id():return uuid.uuid4().hex

def create_app(config=None):
    app=Flask(__name__)
    app.config.update(SECRET_KEY=os.getenv('SECRET_KEY'),MAX_CONTENT_LENGTH=150000,
        SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=True,
        FIREBASE_DATABASE_URL=os.getenv('FIREBASE_DATABASE_URL',''),
        FIREBASE_PROJECT_ID=os.getenv('FIREBASE_PROJECT_ID',''),
        FIREBASE_SERVICE_ACCOUNT=os.getenv('FIREBASE_SERVICE_ACCOUNT',''),
        MAPBOX_TOKEN=os.getenv('MAPBOX_TOKEN',''),FIREBASE_WEB_API_KEY=os.getenv('FIREBASE_WEB_API_KEY',''),STORE=None)
    if config:app.config.update(config)
    if not app.config['SECRET_KEY'] or app.config['SECRET_KEY']=='REPLACE_WITH_RANDOM_SECRET':raise RuntimeError('Set SECRET_KEY in .env; see SETUP.md')
    def db():
        if app.config['STORE'] is None:
            app.config['STORE']=RealtimeStore(app.config['FIREBASE_PROJECT_ID'],app.config['FIREBASE_SERVICE_ACCOUNT'],app.config['FIREBASE_DATABASE_URL'])
        return app.config['STORE']
    def exists(x):return x and not x.get('deleted',False)
    def owner_ok(v):return exists(db().get('users/'+v['owner_id']))
    def body():
        b=request.get_json(silent=True)
        if not isinstance(b,dict):abort(400,'JSON object required')
        return b
    def field(b,k,maxlen=100):
        s=b.get(k)
        if not isinstance(s,str) or not s.strip() or len(s)>maxlen:abort(400,'Invalid '+k)
        return s.strip()
    def valid_id(value):
        if not isinstance(value,str) or len(value)!=32 or any(c not in '0123456789abcdef' for c in value):abort(404)
        return value
    def login_required(fn):
        @wraps(fn)
        def wrapped(*a,**kw):
            if not g.user:abort(401)
            return fn(*a,**kw)
        return wrapped
    def admin_required(fn):
        @wraps(fn)
        @login_required
        def wrapped(*a,**kw):
            if g.user['role']!='admin':abort(403)
            return fn(*a,**kw)
        return wrapped
    def visible(vid):
        v=db().get('vehicles/'+valid_id(vid))
        if not exists(v) or not owner_ok(v) or (g.user['role']!='admin' and v['owner_id']!=g.user['id']):abort(404)
        return v
    def public(v):
        return {k:v.get(k) for k in ('id','name','plate','owner_id','device_id','latitude','longitude','speed','timestamp','mac','fence','fence_locked','blocked','due_date','command','firmware_ack','uploads_enabled')} | {
            'online':bool(v.get('last_seen') and time.time()-v['last_seen']<60),'last_update':v.get('last_seen'),'fix_time':v.get('fix_time'),'gps_fresh':bool(v.get('fix_time') and time.time()-v['fix_time']<15)}
    def live_public(v):
        d=public(v)
        # Avoid retransmitting large boundary geometry on every GPS fix.
        return {k:x for k,x in d.items() if k not in ('fence','mac')}
    def list_vehicles(owner=None):
        rows=db().query('vehicles',where=('owner_id',owner) if owner else None,limit=10000)
        owners={v['owner_id'] for v in rows if exists(v)}
        valid={uid for uid in owners if exists(db().get('users/'+uid))}
        return [v for v in rows if exists(v) and v['owner_id'] in valid]
    def add_user(name,username,password,role):
        uid=new_id();key='usernames/'+ident(username)
        def commit(tx):
            if tx.get(key):abort(409,'Login ID is already used or reserved after deletion')
            tx.put('users/'+uid,dict(id=uid,name=name,username=username,password=generate_password_hash(password),role=role,active=True,deleted=False,session_version=0))
            tx.put(key,{'uid':uid})
        db().atomic(commit);return uid
    @app.before_request
    def identity():
        g.user=None
        if session.get('uid'):
            u=db().get('users/'+valid_id(session['uid']))
            if exists(u) and u.get('active') and session.get('version',0)==u.get('session_version',0):g.user=u
        if request.method in ('POST','PUT','PATCH','DELETE') and request.path!='/api/gps':
            c=request.headers.get('X-CSRF-Token') or request.form.get('csrf','')
            if not c or not secrets.compare_digest(str(c),str(session.get('csrf',''))):abort(400,'Invalid CSRF token. Reload page.')
    @app.after_request
    def headers(r):
        r.headers['Referrer-Policy']='strict-origin-when-cross-origin'
        r.headers['X-Content-Type-Options']='nosniff'
        if not request.path.startswith('/static/'):r.headers['Cache-Control']='no-store'
        return r
    @app.errorhandler(StoreError)
    def database_error(e):
        app.logger.error('Realtime Database %s: %s',e.status,str(e))
        msg='Firebase unavailable or not configured correctly. Check the server error log and run check-firebase.'
        if request.path.startswith('/api/'):return jsonify(error=msg),503
        return render_template('message.html',message=msg),503
    @app.errorhandler(400)
    @app.errorhandler(401)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(429)
    @app.errorhandler(409)
    def error(e):
        if request.path.startswith('/api/'):return jsonify(error=e.description),e.code
        if e.code==401:return redirect('/login')
        return render_template('message.html',message=e.description),e.code
    @app.route('/login',methods=['GET','POST'])
    def login():
        session.setdefault('csrf',secrets.token_urlsafe(32));message=None
        if request.method=='POST':
            name=request.form.get('username','').strip()
            if not db().allow_login(ident(name.lower())):abort(429,'Too many login attempts for this account. Wait 15 minutes.')
            idx=db().get('usernames/'+ident(name))
            u=db().get('users/'+idx['uid']) if idx else None
            if exists(u) and u.get('active') and check_password_hash(u['password'],request.form.get('password','')):
                session.clear();session.update(uid=u['id'],csrf=secrets.token_urlsafe(32),version=u.get('session_version',0));return redirect('/')
            message='Invalid login or suspended account.'
        return render_template('login.html',error=message)
    @app.post('/logout')
    def logout():session.clear();return redirect('/login')
    @app.get('/')
    @login_required
    def index():return render_template('index.html',user=g.user,mapbox_token=app.config['MAPBOX_TOKEN'])
    @app.get('/api/vehicles')
    @login_required
    def vehicles():return jsonify([public(v) for v in list_vehicles(None if g.user['role']=='admin' else g.user['id'])])
    @app.route('/api/users',methods=['GET','POST'])
    @admin_required
    def users():
        if request.method=='POST':
            b=body();password=field(b,'password',256)
            if len(password)<12:abort(400,'Use at least 12 characters')
            uid=add_user(field(b,'name'),field(b,'username'),password,'customer')
            return jsonify(ok=True,id=uid),201
        allv=list_vehicles()
        return jsonify([{k:u[k] for k in ('id','name','username','active')} | {'vehicle_count':sum(v['owner_id']==u['id'] for v in allv)}
                        for u in db().query('users',where=('role','customer'),limit=10000) if exists(u)])
    @app.post('/api/vehicles')
    @admin_required
    def register():
        b=body();name=field(b,'name');plate=field(b,'plate');device=field(b,'device_id');owner=valid_id(b.get('owner_id'))
        mac=str(b.get('mac','')).upper()
        if mac and not re.fullmatch(r'(?:[0-9A-F]{2}:){5}[0-9A-F]{2}',mac):abort(400,'Invalid station MAC')
        vid=new_id();token=secrets.token_urlsafe(32);key='devices/'+ident(device)
        def commit(tx):
            u=tx.get('users/'+owner);index=tx.get(key)
            if not exists(u) or u['role']!='customer':abort(400,'Select an existing customer')
            if index:abort(409,'Device ID already used or reserved after deletion. Use a new ID for a new ownership period.')
            tx.put('vehicles/'+vid,dict(id=vid,owner_id=owner,name=name,plate=plate,device_id=device,
                mac=str(b.get('mac','')).upper(),fence={'kind':'off'},fence_locked=False,blocked=False,control_revision=0,due_date='',legacy=False,uploads_enabled=True,token_hash=ident(token),deleted=False,
                latitude=None,longitude=None,speed=None,timestamp='',last_seen=None))
            tx.put(key,{'vid':vid})
        db().atomic(commit);return jsonify(ok=True,id=vid,token=token),201
    @app.post('/api/users/<uid>/active')
    @admin_required
    def active(uid):
        valid_id(uid);b=body()
        if not isinstance(b.get('active'),bool):abort(400,'active must be boolean')
        def commit(tx):
            u=tx.get('users/'+uid)
            if not exists(u) or u['role']!='customer':abort(404)
            tx.put('users/'+uid,u|{'active':b['active'],'session_version':u.get('session_version',0)+1})
        db().atomic(commit);return jsonify(ok=True)
    def remove(kind,oid,confirm):
        valid_id(oid);path=kind+'/'+oid;job=new_id();actor=g.user['username']
        def commit(tx):
            d=tx.get(path)
            if not exists(d):abort(404)
            if kind=='users' and d['role']=='admin':abort(403,'Admin accounts cannot be deleted here')
            match=d['username'] if kind=='users' else d['device_id']
            if confirm!=match:abort(400,'Type the exact '+('login ID' if kind=='users' else 'device ID'))
            # Keep only a tombstone immediately: revoke password/token and hide record.
            tomb={'id':oid,'deleted':True,'deleted_at':time.time()}
            if kind=='users':
                tomb.update(role='customer',active=False)
                # All vehicle tombstones share this metadata transaction: no upload resurrection.
                for child in tx.query_vehicles(oid):
                    tx.put('vehicles/'+child['id'],{'id':child['id'],'owner_id':oid,'deleted':True})
            else:tomb.update(owner_id=d['owner_id'])
            tx.put(path,tomb)
            if kind=='vehicles':tx.put('live/'+oid,{'id':oid,'owner_id':d['owner_id'],'deleted':True})
            tx.put('deletion_jobs/'+job,{'id':job,'kind':kind,'target':oid,'status':'pending','at':time.time()})
            tx.put('audit/'+job,{'id':job,'actor':actor,'action':'delete_'+kind,'target':oid,'at':time.time()})
        db().atomic(commit)
        return jsonify(ok=True,message='Access revoked. Stored history is queued for permanent cleanup.',cleanup_pending=True)
    @app.delete('/api/vehicles/<vid>')
    @admin_required
    def delete_vehicle(vid):return remove('vehicles',vid,body().get('confirm'))
    @app.delete('/api/users/<uid>')
    @admin_required
    def delete_user(uid):return remove('users',uid,body().get('confirm'))
    @app.post('/api/gps')
    def upload():
        started=time.monotonic();b=body();device=field(b,'device_id');token=request.headers.get('Authorization','').removeprefix('Bearer ')
        now=time.time();samples=b.get('samples',[])
        if not isinstance(samples,list) or len(samples)>20:abort(400,'Maximum 20 stored samples per request')
        def parse(p):
            if not isinstance(p,dict):abort(400,'Invalid point')
            try:
                lat=number(p['latitude'],-90,90);lng=number(p['longitude'],-180,180);speed=number(p.get('speed',0),0,1000)
                ts=p.get('fix_time')
                if ts is None:
                    text=str(p.get('timestamp',''))
                    # Legacy sketch uses UTC DD/MM/YYYY HH:MM:SS.
                    ts=datetime.strptime(text,'%d/%m/%Y %H:%M:%S').replace(tzinfo=timezone.utc).timestamp() if text else now
                ts=number(ts,now-30*86400,now+30)
            except (TypeError,ValueError,KeyError):abort(400,'Invalid GPS point/date; use UTC and history within 30 days')
            ts=int(ts)
            pid=f'{ts:010d}'
            return dict(id=pid,latitude=lat,longitude=lng,speed=speed,fix_time=ts,received=now,timestamp=datetime.fromtimestamp(ts,timezone.utc).isoformat())
        stored=[parse(p) for p in samples]
        live=parse(b) if b.get('gps_valid',True) and 'latitude' in b else None
        fresh=bool(live and abs(now-live['fix_time'])<=15)
        if live:stored.append(live)
        history_step=max(1,int(os.getenv('HISTORY_INTERVAL_SECONDS','5')))
        for point in stored:point['id']=f"{int(point['fix_time'])//history_step*history_step:010d}"
        index=db().get('devices/'+ident(device))
        if not index:abort(403,'Device is not registered')
        def commit(tx):
            v=tx.get('vehicles/'+index['vid'])
            if not exists(v):abort(403,'Vehicle deleted')
            u=tx.get('users/'+v['owner_id'])
            if not exists(u):abort(403,'Owner deleted')
            if not secrets.compare_digest(v.get('token_hash',''),ident(token)):abort(401,'Invalid device token')
            if not v.get('uploads_enabled',True):abort(403,'Device uploads disabled')
            incoming_mac=str(b.get('mac','')).upper()
            if v.get('mac') and incoming_mac!=v['mac']:abort(403,'Station MAC mismatch; update firmware or registration')
            state,cmd=command(v,now,fresh,live['latitude'] if live else None,live['longitude'] if live else None)
            updated=v|{'last_seen':now,'control':state,'command':cmd,'firmware_ack':str(b.get('ack','legacy firmware: no command acknowledgement'))[:150]}
            if live and live['fix_time']>=(v.get('fix_time') or 0):
                updated.update({k:live[k] for k in ('latitude','longitude','speed','timestamp','fix_time')})
            tx.put('vehicles/'+v['id'],updated)
            tx.put('live/'+v['id'],live_public(updated))
            unique={point['id']:point for point in stored}
            for point in unique.values():tx.put('vehicles/'+v['id']+'/points/'+point['id'],point)
            if v.get('command',{}).get('phase')!=cmd['phase']:
                eid=ident(v['id']+str(now))[:32]
                tx.put('vehicles/'+v['id']+'/events/'+eid,{'id':eid,'at':now,'kind':cmd['phase'],'actor':'tracker'})
            return cmd
        cmd=db().atomic(commit,scope='vehicles/'+index['vid']);elapsed=round((time.monotonic()-started)*1000)
        app.logger.info('gps device=%s server_ms=%s points=%s',device,elapsed,len(stored))
        return jsonify(status='success',message='Data received',server_time=now,server_ms=elapsed,command=cmd,stop_request=cmd['stop_request'],engine_cutoff=0)
    @app.get('/api/gps')
    @app.get('/api/location')
    @app.get('/api/latest')
    @login_required
    def location():return jsonify(public(visible(request.args.get('vehicle_id'))))
    @app.get('/api/vehicles/<vid>/history')
    @login_required
    def history(vid):
        visible(vid)
        return jsonify(list(reversed(db().query('vehicles/'+vid+'/points',order='received',limit=2000))))
    @app.post('/api/firebase-session')
    @login_required
    def firebase_session():
        if not app.config['FIREBASE_WEB_API_KEY']:abort(400,'Configure FIREBASE_WEB_API_KEY to enable live Firebase listeners')
        return jsonify(token=db().custom_token(g.user['id'],g.user.get('session_version',0)),uid=g.user['id'],config={
            'apiKey':app.config['FIREBASE_WEB_API_KEY'],'projectId':app.config['FIREBASE_PROJECT_ID'],
            'authDomain':app.config['FIREBASE_PROJECT_ID']+'.firebaseapp.com','databaseURL':app.config['FIREBASE_DATABASE_URL']})
    @app.get('/api/cities')
    @login_required
    def cities():return jsonify([{k:c[k] for k in ('id','name')} for c in db().query('cities',limit=1000)])
    @app.post('/api/cities')
    @admin_required
    def city_add():
        b=body()
        try:geo=geometry(b.get('geometry'))
        except (ValueError,TypeError,KeyError) as e:abort(400,str(e))
        cid=new_id();db().put('cities/'+cid,{'id':cid,'name':field(b,'name'),'geometry':geo})
        return jsonify(ok=True,id=cid)
    @app.post('/api/vehicles/<vid>/fence')
    @login_required
    def fence_save(vid):
        valid_id(vid);b=body();kind=b.get('kind')
        try:
            if kind=='off':f={'kind':'off'}
            elif kind=='radius':f={'kind':kind,'lat':number(b.get('lat'),-90,90),'lng':number(b.get('lng'),-180,180),'km':number(b.get('km'),.05,1000)}
            elif kind=='city':
                city=db().get('cities/'+valid_id(b.get('city_id')))
                if not city:abort(400,'Choose an imported city')
                f={'kind':kind,'city_id':city['id'],'name':city['name'],'geometry':city['geometry']}
            elif kind=='polygon':f={'kind':kind,'geometry':geometry(b.get('geometry'))}
            else:abort(400,'Unknown boundary type')
        except (TypeError,ValueError) as e:abort(400,str(e))
        def commit(tx):
            v=tx.get('vehicles/'+vid)
            if not exists(v):abort(404)
            owner=tx.get('users/'+v['owner_id'])
            if not exists(owner):abort(404)
            if g.user['role']!='admin' and (v['owner_id']!=g.user['id'] or v.get('fence_locked')):abort(403)
            control=dict(v.get('control',{}));control.pop('breach_started',None)
            v=v|{'fence':f,'control':control,'control_revision':v.get('control_revision',0)+1}
            tx.put('vehicles/'+vid,v);tx.put('live/'+vid,live_public(v))
        db().atomic(commit);return jsonify(ok=True)
    @app.post('/api/vehicles/<vid>/controls')
    @admin_required
    def controls(vid):
        valid_id(vid);b=body()
        for k in ('blocked','fence_locked','uploads_enabled'):
            if k in b and not isinstance(b[k],bool):abort(400,k+' must be boolean')
        due=str(b.get('due_date',''))
        if due:
            try:datetime.strptime(due,'%Y-%m-%d')
            except ValueError:abort(400,'Invalid due date')
        rotated=secrets.token_urlsafe(32) if b.get('rotate_token') is True else None
        def commit(tx):
            v=tx.get('vehicles/'+vid)
            if not exists(v):abort(404)
            for k in ('blocked','fence_locked','due_date','uploads_enabled'):
                if k in b:v[k]=b[k]
            if 'blocked' in b:v['control']={}
            if rotated:v.update(token_hash=ident(rotated),legacy=False)
            if 'mac' in b:
                mac=str(b['mac']).upper()
                if mac and not re.fullmatch(r'(?:[0-9A-F]{2}:){5}[0-9A-F]{2}',mac):abort(400,'Invalid MAC')
                v['mac']=mac
            v['control_revision']=v.get('control_revision',0)+1
            tx.put('vehicles/'+vid,v);tx.put('live/'+vid,live_public(v))
        db().atomic(commit);return jsonify(ok=True,token=rotated)
    @app.post('/api/users/<uid>/password')
    @admin_required
    def reset_password(uid):
        valid_id(uid);p=field(body(),'password',256)
        if len(p)<12:abort(400,'Use at least 12 characters')
        def commit(tx):
            u=tx.get('users/'+uid)
            if not exists(u) or u['role']!='customer':abort(404)
            tx.put('users/'+uid,u|{'password':generate_password_hash(p),'session_version':u.get('session_version',0)+1})
        db().atomic(commit);return jsonify(ok=True)
    @app.get('/api/vehicles/<vid>/events')
    @login_required
    def events(vid):
        visible(vid);return jsonify(db().query('vehicles/'+vid+'/events',order='at',limit=100))
    @app.get('/api/vehicles/<vid>/journey')
    @login_required
    def journey(vid):
        visible(vid)
        try:
            start=datetime.strptime(request.args.get('date',''),'%Y-%m-%d').replace(tzinfo=timezone(timedelta(hours=5))).timestamp()
            cursor=json.loads(request.args['cursor']) if request.args.get('cursor') else None
            if cursor is not None:
                if not isinstance(cursor,list) or len(cursor)!=2 or not isinstance(cursor[1],str) or not re.fullmatch('[0-9]{10}',cursor[1]):raise ValueError()
                cursor[0]=number(cursor[0],start,start+86400)
        except (ValueError,TypeError,KeyError):abort(400,'Invalid date or cursor')
        points=db().history_page(vid,start,start+86400,cursor,500)
        nxt=[points[-1]['fix_time'],points[-1]['id']] if len(points)==500 else None
        return jsonify(points=points,next_cursor=nxt)
    @app.post('/api/password')
    @login_required
    def own_password():
        b=body();password=field(b,'password',256)
        if len(password)<12:abort(400,'Use at least 12 characters')
        uid=g.user['id']
        def commit(tx):
            u=tx.get('users/'+uid)
            if not exists(u) or not check_password_hash(u['password'],str(b.get('current',''))):abort(403,'Current password is incorrect')
            version=u.get('session_version',0)+1
            tx.put('users/'+uid,u|{'password':generate_password_hash(password),'session_version':version})
            return version
        session['version']=db().atomic(commit)
        return jsonify(ok=True)
    @app.cli.command('prune-history')
    @click.option('--days',default=7,type=click.IntRange(1,30),show_default=True)
    def prune_history(days):
        """Permanently delete points/events older than DAYS; run daily."""
        db().prune_login_limits()
        cutoff=time.time()-days*86400
        for v in db().query('vehicles',limit=10000):
            for kind,fieldname in [('points','fix_time'),('events','at')]:
                while True:
                    rows=db().older_history(v['id'],kind,fieldname,cutoff,200)
                    if not rows:break
                    db().delete_many(['vehicles/'+v['id']+'/'+kind+'/'+r['id'] for r in rows])
        click.echo('Old history removed. Active vehicle/account records retained.')
    @app.get('/api/health')
    def health():return jsonify(status='healthy',storage='realtime-database')
    @app.cli.command('create-admin')
    @click.option('--username',prompt=True)
    @click.option('--name',prompt=True)
    @click.password_option(confirmation_prompt=True)
    def create_admin(username,name,password):
        if not username.strip() or not name.strip() or len(password)<12:raise click.ClickException('Name/login required; password at least 12 characters')
        add_user(name.strip(),username.strip(),password,'admin');click.echo('Administrator created in Realtime Database.')
    @app.cli.command('check-firebase')
    def check_firebase():
        path='diagnostics/'+new_id();db().put(path,{'ok':True});assert db().get(path)['ok'];db().delete_many([path])
        click.echo('Realtime Database read/write/delete succeeded.')
    @app.cli.command('check-live')
    def check_live():
        """Verify custom-token sign-in without printing tokens or private keys."""
        import requests
        admins=db().query('users',where=('role','admin'),limit=10)
        admins=[u for u in admins if exists(u) and u.get('active')]
        if not admins:raise click.ClickException('Run create-admin first.')
        key=app.config['FIREBASE_WEB_API_KEY']
        if not key:raise click.ClickException('Set FIREBASE_WEB_API_KEY from the SAME project web app.')
        u=admins[0]
        try:
            r=requests.post('https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken',params={'key':key},
                json={'token':db().custom_token(u['id'],u.get('session_version',0)),'returnSecureToken':True},timeout=20)
            result=r.json()
        except (requests.RequestException,ValueError):raise click.ClickException('Firebase Authentication connection failed. Check outbound access.')
        if not r.ok:
            error=str(result.get('error',{}).get('message','Unknown Authentication error')).replace(key,'[hidden]')
            raise click.ClickException(error+' — initialize Authentication with Get started and verify all Firebase settings use the same project.')
        click.echo('Firebase custom-token sign-in succeeded. Browser live authentication is configured.')
    @app.cli.command('purge-deleted')
    def purge_deleted():
        """Run after deletions or schedule regularly. Idempotent and resumable."""
        def purge_vehicle(vid):
            path='vehicles/'+vid
            def mark(tx):
                v=tx.get(path)
                if v and not v.get('deleted'):tx.put(path,{'id':vid,'owner_id':v['owner_id'],'deleted':True})
            db().atomic(mark)
            while True:
                points=db().query(path+'/points',limit=200)
                if not points:break
                db().delete_many([path+'/points/'+p['id'] for p in points])
            
            while True:
                events=db().query(path+'/events',limit=200)
                if not events:break
                db().delete_many([path+'/events/'+e['id'] for e in events])
            db().delete_many([path,'live/'+vid])
        for job in db().query('deletion_jobs',where=('status','pending'),limit=100):
            # Let bounded in-flight uploads finish before physical cleanup. Access is already revoked.
            if time.time()-job['at']<1200:
                click.echo('Waiting for in-flight requests: '+job['id']);continue
            if job['kind']=='users':
                while True:
                    vs=db().query('vehicles',where=('owner_id',job['target']),limit=200)
                    if not vs:break
                    for v in vs:purge_vehicle(v['id'])
                db().delete_many(['users/'+job['target']])
            else:purge_vehicle(job['target'])
            db().put('deletion_jobs/'+job['id'],job|{'status':'done','finished_at':time.time()})
            click.echo('Cleaned '+job['id'])
        click.echo('Cleanup pass complete. Username/device-ID reservations and audit metadata retained.')
    return app

# Flask --app app auto-discovers create_app. WSGI calls it explicitly.
if __name__=='__main__':create_app().run()
