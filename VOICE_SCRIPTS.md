# DFPlayer voice tracks (audio files must be recorded separately)

Set AUDIO_ENABLED true after connecting the DFPlayer; no voice MP3s are included.
Save these recordings on its microSD in /mp3/ with the exact filenames.

1. `0001.mp3` — boundary breach, first 60 seconds:
   **Urdu:** آپ مقررہ حدود سے باہر ہیں۔ براہِ کرم ایک منٹ کے اندر مقررہ حدود میں واپس آ جائیں۔
   **English:** You are outside the permitted area. Please return within one minute.

2. `0002.mp3` — still outside, next 60 seconds:
   **Urdu:** آپ ابھی بھی مقررہ حدود سے باہر ہیں۔ براہِ کرم محفوظ جگہ پر گاڑی سائیڈ میں روکیں۔ ایک منٹ بعد دوبارہ اسٹارٹ کرنے پر پابندی کی درخواست فعال ہو جائے گی۔
   **English:** You are still outside the permitted area. Please pull over safely. A restart restriction will be requested in one minute.

3. `0003.mp3` — administrator manual block warning:
   **Urdu:** منتظم نے اس گاڑی پر پابندی کی درخواست دی ہے۔ براہِ کرم محفوظ جگہ پر رکیں اور منتظم سے رابطہ کریں۔ دس منٹ بعد دوبارہ اسٹارٹ کرنے پر پابندی کی درخواست فعال ہو جائے گی۔
   **English:** The administrator has requested a restriction for this vehicle. Please stop safely and contact the administrator. A restart restriction will be requested after ten minutes.

4. `0004.mp3` — pending restart restriction:
   **Urdu:** دوبارہ اسٹارٹ کرنے پر پابندی کی درخواست فعال ہے۔ براہِ کرم منتظم سے رابطہ کریں۔
   **English:** A restart restriction has been requested. Please contact the administrator.

These scripts describe a requested state. This firmware has no physical engine or starter interlock. It never cuts a running engine. Do not record claims that the supplied firmware will stop the engine.
