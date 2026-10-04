"""Pure boundary validation and safe command state machine. No relay control."""
import math,json

def distance(a,b,c,d):
    p,q=math.radians(a),math.radians(c);dp=q-p;dl=math.radians(d-b)
    h=math.sin(dp/2)**2+math.cos(p)*math.cos(q)*math.sin(dl/2)**2
    return 6371000*2*math.asin(min(1,math.sqrt(h)))

def number(x,low,high):
    if isinstance(x,bool):raise ValueError('Expected a number')
    v=float(x)
    if not math.isfinite(v) or not low<=v<=high:raise ValueError('Coordinate/radius outside valid range')
    return v

def geometry(g):
    if not isinstance(g,dict):raise ValueError('GeoJSON geometry required')
    if g.get('type')=='Feature':g=g.get('geometry',{})
    if not isinstance(g,dict):raise ValueError('GeoJSON geometry required')
    if g.get('type') not in ('Polygon','MultiPolygon'):raise ValueError('Use Polygon or MultiPolygon GeoJSON')
    polygons=[g.get('coordinates')] if g['type']=='Polygon' else g.get('coordinates')
    if not isinstance(polygons,list) or not polygons:raise ValueError('Empty geometry')
    count=0
    for p in polygons:
        if not isinstance(p,list) or not p:raise ValueError('Empty polygon')
        for ring in p:
            if not isinstance(ring,list) or len(ring)<4 or ring[0]!=ring[-1]:raise ValueError('Each ring needs at least 4 coordinates and must be closed')
            for xy in ring:
                if not isinstance(xy,list) or len(xy)!=2:raise ValueError('Use [longitude, latitude] pairs')
                xy[0]=number(xy[0],-180,180);xy[1]=number(xy[1],-90,90);count+=1
    if count>2000 or len(json.dumps(g))>100000:raise ValueError('Boundary too large; simplify to <=2000 vertices and 100 KB')
    return g

def ring_inside(ring,x,y):
    inside=False
    for a,b in zip(ring,ring[1:]):
        ax,ay=a;bx,by=b
        if abs((x-ax)*(by-ay)-(y-ay)*(bx-ax))<1e-10 and min(ax,bx)<=x<=max(ax,bx) and min(ay,by)<=y<=max(ay,by):return True
        if (ay>y)!=(by>y) and x<(bx-ax)*(y-ay)/(by-ay)+ax:inside=not inside
    return inside

def inside(f,lat,lng):
    if f.get('kind','off')=='off':return True
    if f['kind']=='radius':return distance(lat,lng,f['lat'],f['lng'])<=f['km']*1000
    g=f['geometry'];ps=[g['coordinates']] if g['type']=='Polygon' else g['coordinates']
    return any(ring_inside(p[0],lng,lat) and not any(ring_inside(r,lng,lat) for r in p[1:]) for p in ps)

def command(v,now,fresh,lat=None,lng=None):
    """Timers use server elapsed time, only fresh GPS advances a fence decision."""
    state=dict(v.get('control',{}));phase='normal';track=0;remaining=0
    if v.get('last_seen') and now-v['last_seen']>15:state.pop('breach_started',None)
    if v.get('blocked',False):
        start=state.get('manual_started')
        if start is None:start=now
        state['manual_started']=start;remaining=max(0,600-int(now-start))
        phase='manual_warning' if remaining else 'pending_restart_inhibit';track=3 if remaining else 4
    else:
        state.pop('manual_started',None)
        if not fresh:
            phase='gps_unavailable';state.pop('breach_started',None)
        elif inside(v.get('fence',{'kind':'off'}),lat,lng):state.pop('breach_started',None)
        else:
            start=state.get('breach_started')
            if start is None:start=now
            state['breach_started']=start;elapsed=max(0,int(now-start))
            phase='return_warning' if elapsed<60 else 'pull_over' if elapsed<120 else 'pending_restart_inhibit'
            remaining=max(0,(60 if elapsed<60 else 120)-elapsed);track=1 if elapsed<60 else 2 if elapsed<120 else 4
    bit=1 if phase=='pending_restart_inhibit' else 0
    return state,{'phase':phase,'restart_inhibit_requested':bit,'stop_request':bit,'engine_cutoff':0,
        'voice_track':track,'seconds_remaining':remaining,'command_id':f"{v.get('control_revision',0)}:{phase}",
        'valid_for_seconds':15,'interlock_installed':False}
