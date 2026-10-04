"""An explicit simulated upload to YOUR configured server; does not use real GPS."""
import getpass,time,requests
url=input('Full https://.../api/gps URL: ').strip()
if not url.startswith('https://') or not url.endswith('/api/gps'):raise SystemExit('Use the HTTPS /api/gps URL')
device=input('Registered device ID: ').strip()
mac=input('Registered station MAC: ').strip().upper()
token=getpass.getpass('Device token (hidden): ')
lat=float(input('SIMULATED latitude: '));lng=float(input('SIMULATED longitude: '))
if input('This writes a simulated vehicle position. Type SEND: ')!='SEND':raise SystemExit('Cancelled')
try:
 r=requests.post(url,json={'device_id':device,'mac':mac,'latitude':lat,'longitude':lng,'speed':0,'fix_time':int(time.time()),'ack':'SIMULATOR — not physical GPS'},headers={'Authorization':'Bearer '+token},timeout=30)
 print('HTTP:',r.status_code);print(r.text[:2000])
except requests.RequestException:print('Connection failed. Check exact hostname, HTTPS certificate and network.')
