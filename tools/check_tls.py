"""Inspect a server's verified TLS connection from a PC, without device credentials."""
import ssl,socket
host=input('Hostname only, e.g. yourname.pythonanywhere.com: ').strip()
if not host or '/' in host or ':' in host:raise SystemExit('Enter hostname only')
try:
 with socket.create_connection((host,443),timeout=15) as raw:
  with ssl.create_default_context().wrap_socket(raw,server_hostname=host) as tls:
   cert=tls.getpeercert()
   print('Verified:',tls.version())
   print('Issuer:',cert.get('issuer'))
   print('Expires:',cert.get('notAfter'))
except (OSError,ssl.SSLError):raise SystemExit('TLS/network verification failed. Do not disable verification on the tracker.')
