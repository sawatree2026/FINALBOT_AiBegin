# ATHENA UNIFIED CROSS-PLATFORM MEMORY & SYNC RULE

1. **Central Brain Hub (Point A):**
   - ศูนย์รวมตัวตน ความจำ และระบบปฏิบัติการข้ามแพลตฟอร์มอยู่ที่ `C:\Users\BUSOLOVE\.gemini\athena-gemini\`
   - โฟลเดอร์นี้รองรับ Multi-Project และออกแบบให้ซิงค์ผ่าน Google Drive ไปยัง Gemini Web, Gemini Windows Desktop และ Gemini Spark
   - บริบทสรุปย่อสดถูกแคชไว้ที่ `C:\Users\BUSOLOVE\.gemini\athena-gemini\sessions\context_cache.md`

2. **Workspace Test Point (Point B):**
   - จุดทดสอบชั่วคราวในโปรเจกต์คือ `E:\FINALBOT_AiBegin\athena_traderist\` (เปลี่ยนชื่อจาก Athena_trader เดิม)
   - ไฟล์สถานะ `PROJECT_STATE.md` และ JSON สัญญาณในจุด B ซิงค์ตรงกับ `projects/FINALBOT_AiBegin/` ในจุด A เสมอ

3. **Zero Redundant Reads:**
   - เมื่อเริ่มต้นเซสชัน ไม่ว่าจะบน Antigravity CLI, IDE, หรือ Web ให้อ่านสถานะจาก `PROJECT_STATE.md` หรือ `context_cache.md` โดยตรง
   - ห้ามสแกนไฟล์ซ้ำซ้อนในเรื่องที่มีบันทึกไว้ในสมองกลางแล้ว
