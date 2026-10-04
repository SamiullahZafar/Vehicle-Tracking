/* ESP8266 NodeMCU / ESP32 GPS tracker. No relay or engine cutoff output.
   Libraries: TinyGPSPlus, ArduinoJson 7, DFRobotDFPlayerMini.
   ESP8266: GPS TX -> D5 / GPIO14. Configurable ESP32 pins in config.h.
*/
#include <Arduino.h>
#include <utility>
#if defined(ESP8266)
#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClientSecureBearSSL.h>
#include <SoftwareSerial.h>
#else
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#endif
#include <LittleFS.h>
#include <TinyGPSPlus.h>
#include <ArduinoJson.h>
#include <DFRobotDFPlayerMini.h>
#include <time.h>
#include <sys/time.h>
#include "config.h"
TinyGPSPlus gps;
DFRobotDFPlayerMini audio;
#if defined(ESP8266)
SoftwareSerial gpsPort,audioPort;
BearSSL::X509List trust(ROOT_CA);
BearSSL::Session tlsSession;
bool fragmentProbeDone=false;
uint16_t tlsReceiveBytes=16384;
#else
HardwareSerial gpsPort(1),audioPort(2);
#endif
unsigned long lastSample=0,lastUpload=0,lastWifi=0,lastReconnect=0,lastStatus=0,lastCommand=0,lastVoice=0;
unsigned long retryMs=1000;
String deviceID,mac,phase="starting",commandID="",lastVoiceID="";
bool connected=false,audioReady=false;
int queued=0,restartRequest=0,queueDropped=0;
const int QUEUE_LIMIT=1000,BATCH=2;
void pumpGPS(){while(gpsPort.available())gps.encode(gpsPort.read());}
bool fresh(){return gps.location.isValid()&&gps.location.age()<2500&&gps.time.isValid()&&gps.time.age()<2500&&gps.date.isValid()&&gps.date.age()<3000&&gps.speed.isValid()&&gps.speed.age()<2500;}
time_t fixTime(){tm t={};t.tm_year=gps.date.year()-1900;t.tm_mon=gps.date.month()-1;t.tm_mday=gps.date.day();t.tm_hour=gps.time.hour();t.tm_min=gps.time.minute();t.tm_sec=gps.time.second();return mktime(&t);}
void makePoint(JsonObject p){p["latitude"]=gps.location.lat();p["longitude"]=gps.location.lng();p["speed"]=gps.speed.isValid()&&gps.speed.age()<2500?gps.speed.kmph():0;p["fix_time"]=(long long)fixTime();}
void storageReport();
void capture(){
 if(!fresh()||fixTime()<1700000000)return;
 String path="/q/"+String((unsigned long)fixTime())+".json";if(LittleFS.exists(path))return;
#if defined(ESP8266)
 FSInfo info;LittleFS.info(info);size_t space=info.totalBytes-info.usedBytes;
#else
 size_t space=LittleFS.totalBytes()-LittleFS.usedBytes();
#endif
 if(queued>=QUEUE_LIMIT||space<4096){queueDropped++;if(queueDropped==1||queueDropped%30==0)storageReport();return;}
 JsonDocument p;makePoint(p.to<JsonObject>());File f=LittleFS.open(path,"w");if(!f)return;
 size_t expected=measureJson(p),written=serializeJson(p,f);f.close();if(written==expected)queued++;else LittleFS.remove(path);
}
void wifiTick(){unsigned long now=millis();if(WiFi.status()==WL_CONNECTED){if(!connected){connected=true;Serial.print("WiFi CONNECTED. IP: ");Serial.println(WiFi.localIP());Serial.println("Station MAC: "+mac);Serial.println("Device ID: "+deviceID);}return;}
 if(connected){connected=false;Serial.println("WiFi lost. Queued GPS recording continues; server commands unavailable.");}
 if(now-lastWifi>=2000){lastWifi=now;Serial.printf("WiFi connecting... status=%d\n",(int)WiFi.status());}
 if(now-lastReconnect>=30000){lastReconnect=now;WiFi.reconnect();}
}
// Bounded sink: HTTPClient decodes chunked responses without an unbounded String.
class ReplySink : public Stream {
 public:
 String text;
 bool failed=false;
 int available() override{return 0;}
 int read() override{return -1;}
 int peek() override{return -1;}
 void flush() override{}
 size_t write(uint8_t value) override{return write(&value,1);}
 size_t write(const uint8_t *data,size_t size) override{
  if(size>4096-text.length()){failed=true;return 0;}
  if(!text.concat((const char*)data,(unsigned int)size)){failed=true;return 0;}
  return size;
 }
};
void storageReport(){
#if defined(ESP8266)
 FSInfo info;if(LittleFS.info(info))Serial.printf("FLASH total=%lu used=%lu free=%lu queue=%d dropped=%d\n",(unsigned long)info.totalBytes,(unsigned long)info.usedBytes,(unsigned long)(info.totalBytes-info.usedBytes),queued,queueDropped);
#else
 Serial.printf("FLASH total=%lu used=%lu free=%lu queue=%d dropped=%d\n",(unsigned long)LittleFS.totalBytes(),(unsigned long)LittleFS.usedBytes(),(unsigned long)(LittleFS.totalBytes()-LittleFS.usedBytes()),queued,queueDropped);
#endif
}
void memoryReport(const char *label){
#if defined(ESP8266)
 Serial.printf("%s heap=%u largest_block=%u fragmentation=%u%% wifi=%d\n",label,(unsigned)ESP.getFreeHeap(),(unsigned)ESP.getMaxFreeBlockSize(),(unsigned)ESP.getHeapFragmentation(),(int)WiFi.status());
#else
 Serial.printf("%s heap=%u wifi=%d\n",label,ESP.getFreeHeap(),(int)WiFi.status());
#endif
}
void upload(){
 if(WiFi.status()!=WL_CONNECTED)return;
 if(time(nullptr)<1700000000){
  if(fresh()&&fixTime()>1700000000){timeval tv={fixTime(),0};settimeofday(&tv,nullptr);}
  else{Serial.println("Waiting for UTC time (NTP/GPS) before HTTPS.");return;}
 }
 String url=SERVER_URL;
 if(!url.startsWith("https://")){Serial.println("SERVER_URL must start with https://");return;}
 int slash=url.indexOf('/',8);String host=url.substring(8,slash<0?url.length():slash);
 IPAddress resolved;
 memoryReport("BEFORE_DNS");
 if(WiFi.hostByName(host.c_str(),resolved)!=1){
  Serial.println("DNS_FAILED: "+host);retryMs=10000;return;
 }
 Serial.print("DNS_OK "+host+" -> ");Serial.println(resolved);Serial.printf("UTC_epoch=%lu\n",(unsigned long)time(nullptr));
#if defined(ESP8266)
 // Never shrink the receive buffer without server negotiation support.
 if(!fragmentProbeDone){
  Serial.println("Checking server TLS fragment negotiation once...");
  bool supported=BearSSL::WiFiClientSecure::probeMaxFragmentLength(host.c_str(),443,4096);
  tlsReceiveBytes=supported?4096:16384;fragmentProbeDone=true;
  Serial.printf("MFLN=%s TLS_receive_bytes=%u\n",supported?"supported":"not confirmed",tlsReceiveBytes);
 }
#endif
 pumpGPS(); // DNS/probe may have taken time. Refresh the UART parser before sampling.
 String paths[BATCH],payload;int count=0;
 { // Release JSON allocations AND LittleFS directory state before TLS allocation.
  JsonDocument req;req["device_id"]=deviceID;req["mac"]=mac;
  req["ack"]=commandID+";restart_request="+String(restartRequest)+";interlock_not_installed";
  req["gps_valid"]=fresh();if(fresh())makePoint(req.as<JsonObject>());
  JsonArray samples=req["samples"].to<JsonArray>();
#if defined(ESP8266)
  Dir dir=LittleFS.openDir("/q");
  while(count<BATCH&&dir.next()){
   if(!dir.isFile())continue;
   String path=dir.fileName();if(!path.startsWith("/q/"))path="/q/"+path;
   File f=dir.openFile("r");JsonDocument point;auto err=deserializeJson(point,f);f.close();
   long long ts=point["fix_time"]|0LL;
   if(err||ts<(long long)time(nullptr)-30LL*86400){if(LittleFS.remove(path)){queued=max(0,queued-1);queueDropped++;}Serial.println("Discarded corrupt/expired queued sample (server history window: 30 days)");}
   else{samples.add(point.as<JsonObjectConst>());paths[count++]=path;}yield();
  }
#else
  File dir=LittleFS.open("/q"),entry=dir.openNextFile();
  while(entry&&count<BATCH){String name=entry.name();String path="/q/"+name.substring(name.lastIndexOf('/')+1);JsonDocument point;auto err=deserializeJson(point,entry);entry.close();if(!err){samples.add(point.as<JsonObjectConst>());paths[count++]=path;}entry=dir.openNextFile();}entry.close();dir.close();
#endif
  if(req.overflowed()){Serial.println("JSON memory full; queue retained");return;}
  if(!payload.reserve(measureJson(req)+1)){Serial.println("Payload allocation failed; queue retained");return;}
  serializeJson(req,payload);
 }
 memoryReport("BEFORE_TLS");
 String response;int code=0;
 { // Per-attempt lifetime frees TLS buffers even after a failed connection.
#if defined(ESP8266)
  BearSSL::WiFiClientSecure secure;
  secure.setTrustAnchors(&trust);secure.setSession(&tlsSession);
   secure.setBufferSizes(tlsReceiveBytes,512);
#else
  WiFiClientSecure secure;secure.setCACert(ROOT_CA);
#endif
  HTTPClient http;http.setTimeout(15000);http.setReuse(false);
  if(!http.begin(secure,SERVER_URL)){Serial.println("Invalid server URL");return;}
  http.addHeader("Content-Type","application/json");
  if(String(DEVICE_TOKEN).length())http.addHeader("Authorization",String("Bearer ")+DEVICE_TOKEN);
  unsigned long begin=millis();code=http.POST(payload);unsigned long elapsed=millis()-begin;
  Serial.printf("HTTP=%d elapsed_ms=%lu RSSI=%d heap_during_tls=%u queue=%d\n",code,elapsed,WiFi.RSSI(),ESP.getFreeHeap(),queued);
  if(code<0){
   Serial.println(HTTPClient::errorToString(code));
#if defined(ESP8266)
   char err[180]={0};int sslCode=secure.getLastSSLError(err,sizeof(err));
   Serial.printf("TLS_error=%d detail=%s\n",sslCode,err);
   if(sslCode==0)Serial.println("No specific BearSSL error recorded; this does not prove certificate failure.");
#endif
  }else if(http.getSize()<=4096){
   ReplySink sink;int bytes=http.writeToStream(&sink);
   if(bytes>=0&&!sink.failed)response=std::move(sink.text);
   else Serial.println("Response read failed/too large; queue retained.");
  }else Serial.println("Response exceeds 4096 bytes; queue retained.");
  http.end();secure.stop();
 }
 memoryReport("AFTER_TLS_RELEASE");
 if(code==200){
  JsonDocument reply;auto err=deserializeJson(reply,response);
  if(!err&&reply["status"]=="success"&&reply["command"].is<JsonObject>()){
   for(int i=0;i<count;i++)if(LittleFS.remove(paths[i]))queued=max(0,queued-1);
   JsonObject cmd=reply["command"];int bit=cmd["restart_inhibit_requested"]|0;
   restartRequest=bit==1?1:0;phase=String(cmd["phase"]|"unknown");commandID=String(cmd["command_id"]|"");lastCommand=millis();
   int track=cmd["voice_track"]|0;
   if(track>=1&&track<=4&&(commandID!=lastVoiceID||millis()-lastVoice>=60000)){lastVoiceID=commandID;lastVoice=millis();Serial.printf("VOICE TRACK %d | %s\n",track,phase.c_str());if(audioReady)audio.playMp3Folder(track);}
   Serial.printf("restart_inhibit_requested=%d engine_cutoff=0 phase=%s server_ms=%d\n",restartRequest,phase.c_str(),reply["server_ms"]|0);
   retryMs=SEND_INTERVAL_MS;
  }else{Serial.println("Invalid server response; queue retained");retryMs=5000;}
 }else{
  retryMs=min(30000UL,max(2000UL,retryMs*2));
  if(response.length())Serial.println(response.substring(0,350));
  if(code==401)Serial.println("Wrong/missing original vehicle token (not its stored hash).");
  if(code==403)Serial.println("Check registered Device ID, station MAC and deleted owner/vehicle.");
  if(code<0){
   // No credentials sent. Distinguishes TCP reachability from TLS/HTTP failure.
   WiFiClient tcp;unsigned long start=millis();bool reachable=tcp.connect(resolved,443);
   Serial.printf("TCP_443=%s elapsed_ms=%lu wifi=%d\n",reachable?"reachable":"failed",millis()-start,(int)WiFi.status());tcp.stop();
  }
 }
 // No engine relay output. Samples are removed only after confirmed acceptance.
}
void setup(){
 Serial.begin(115200);delay(500);Serial.println("FleetRTDB ESP8266 D5 v1");setenv("TZ","UTC0",1);tzset();
#if defined(ESP8266)
 gpsPort.begin(9600,SWSERIAL_8N1,GPS_RX_PIN,-1,false,512,1024);
 LittleFSConfig fs;fs.setAutoFormat(false);LittleFS.setConfig(fs);
 if(!LittleFS.begin()){
#else
 gpsPort.begin(9600,SERIAL_8N1,GPS_RX_PIN,GPS_TX_PIN);
 if(!LittleFS.begin(false)){
#endif
  Serial.println("LittleFS mount failed. Format ONCE with the separate formatter on a new board; this erases queued history.");while(true)delay(1000);
 }
 LittleFS.mkdir("/q");
#if defined(ESP8266)
 Dir dir=LittleFS.openDir("/q");while(dir.next())if(dir.isFile())queued++;
#else
 File dir=LittleFS.open("/q"),e=dir.openNextFile();while(e){queued++;e.close();e=dir.openNextFile();}dir.close();
#endif
 if(AUDIO_ENABLED){
#if defined(ESP8266)
 audioPort.begin(9600,SWSERIAL_8N1,-1,AUDIO_TX_PIN);
#else
 audioPort.begin(9600,SERIAL_8N1,-1,AUDIO_TX_PIN);
#endif
 audio.begin(audioPort,false,false);audio.volume(22);audioReady=true;
 }
 WiFi.mode(WIFI_STA);WiFi.persistent(false);
#if defined(ESP8266)
 WiFi.setSleepMode(WIFI_NONE_SLEEP);
#else
 WiFi.setSleep(false);
#endif
 mac=WiFi.macAddress();deviceID=String(DEVICE_ID).length()?String(DEVICE_ID):mac;WiFi.setAutoReconnect(true);WiFi.begin(WIFI_SSID,WIFI_PASSWORD);
 storageReport();configTime(0,0,"pool.ntp.org","time.google.com");Serial.println("Server: "+String(SERVER_URL));Serial.println("Register ID: "+deviceID+" MAC: "+mac);
}
void loop(){pumpGPS();wifiTick();unsigned long now=millis();
 if(lastCommand&&now-lastCommand>15000){restartRequest=0;phase="command_expired";commandID="expired";lastCommand=0;Serial.println("Command expired: restart request=0; no physical interlock installed.");}
 if(now-lastSample>=SAMPLE_INTERVAL_MS){lastSample=now;capture();}
 if(now-lastStatus>=5000){lastStatus=now;Serial.printf("GPS=%s lat=%.6f lng=%.6f queue=%d dropped=%d\n",fresh()?"fresh":"waiting",gps.location.lat(),gps.location.lng(),queued,queueDropped);}
 if(now-lastUpload>=retryMs){lastUpload=now;upload();}
 delay(2);
}
