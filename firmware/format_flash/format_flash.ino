// Run ONLY if LittleFS fails to mount on a new board.
// This erases ALL queued GPS history and cached settings on the tracker.
#include <Arduino.h>
#include <LittleFS.h>
void setup() {
 Serial.begin(115200);delay(1500);
 Serial.println("WARNING: type FORMAT in Serial Monitor to erase tracker storage.");
 Serial.setTimeout(1000);
}
void loop() {
 if(!Serial.available()){delay(10);return;}
 String answer=Serial.readStringUntil('\n');answer.trim();
 if(answer!="FORMAT"){Serial.println("Not formatted. Type FORMAT to confirm.");return;}
 Serial.println(LittleFS.format()?"Format complete. Upload FleetTracker now.":"Format failed. Check the flash layout.");
 while(true) delay(1000);
}
