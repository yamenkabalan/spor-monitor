# تشغيل المراقب 24/7 على GitHub Actions (مجاناً وبدون جهاز)

الفكرة: GitHub رح يشغّل السكريبت بالسحابة كل ~7 دقائق، ويبعتلك التنبيهات عالتلجرام —
حتى لو اللابتوب مطفي. بياناتك السرية بتنحفظ بمكان مشفّر (Secrets) **مو بالكود**.

> ⚠️ مهم: **لا ترفع ملف `config.json` أبداً** على GitHub (فيه كلمة سرك).
> بس ارفع الملفات المذكورة تحت.

---

## الملفات اللي رح ترفعها (3 بس)
- `monitor.py`
- `requirements.txt`
- `.github/workflows/monitor.yml`

كلهن موجودين بمجلد `Desktop\spor`.

---

## الخطوات

### 1) حساب GitHub
إذا ما عندك، اعمل حساب مجاني من [github.com](https://github.com).

### 2) اعمل مستودع (Repository) جديد
- من github.com اضغط **+** (فوق يمين) → **New repository**
- الاسم: مثلاً `spor-monitor`
- اختر **Public** (مهم — عشان تشغيل مجاني بلا حدود)
- ✅ فعّل **Add a README file**
- اضغط **Create repository**

### 3) ضيف بياناتك السرية (Secrets)
داخل المستودع: **Settings** → (يسار) **Secrets and variables** → **Actions** →
اضغط **New repository secret** وضيف هدول الأربعة، وحدة وحدة:

| Name (بالضبط هيك) | Secret (القيمة) |
|---|---|
| `SPOR_TC` | `99079970178` |
| `SPOR_PASSWORD` | `yamen.sy1231` |
| `TELEGRAM_TOKEN` | `8522596750:AAFw8RaKYq-EedqnwziqO0nm3OHe9jPFbvI` |
| `TELEGRAM_CHAT_ID` | `-1003623659028` |

### 4) ارفع `monitor.py` و `requirements.txt`
- بالصفحة الرئيسية للمستودع: **Add file** → **Upload files**
- اسحب الملفين `monitor.py` و `requirements.txt` من مجلد `Desktop\spor`
- اضغط **Commit changes**

### 5) اعمل ملف الـworkflow
- **Add file** → **Create new file**
- بخانة الاسم اكتب بالضبط:  `.github/workflows/monitor.yml`
- انسخ محتوى الملف `.github/workflows/monitor.yml` من مجلدك والصقه (أو انسخه من تحت)
- اضغط **Commit changes**

### 6) شغّله وجرّبه
- روح على تبويب **Actions** (فوق) → إذا طلب تفعيل، فعّله
- اضغط على **Spor Istanbul Monitor** (يسار) → زر **Run workflow** → **Run workflow**
- انتظر دقيقة-دقيقتين، وراقب قروب التلجرام — لازم توصلك رسالة الحالة بالتركي 🇹🇷

خلص! من هلأ بيشتغل تلقائياً كل ~7 دقائق، 24/7، بدون أي جهاز.

---

## ملاحظات

- **الوقت:** GitHub بيشغّله كل ~7 دقائق بس أحياناً بيتأخر شوي (طبيعي عندهم).
- **إيقاف رسائل الحالة الدورية:** إذا صارت كتير، روح Settings → Secrets and variables →
  **Variables** → New variable: الاسم `HEARTBEAT` والقيمة `false`.
  هيك بيسكت، وبس يبعتلك لما يصير مكان 🟢 أخضر.
- **بعد 60 يوم بلا نشاط** GitHub بيوقف الجدولة تلقائياً — بيكفي تعمل أي تعديل بسيط
  بالمستودع (Commit) عشان يرجع يشتغل.
- **تعديل البيانات لاحقاً** (كلمة سر جديدة مثلاً): بس عدّل قيمة الـSecret المناسب — مو الكود.
- الكمبيوتر المحلي و`run.bat` ما عاد لازمينك بعد هيك (بس بيضلوا شغّالين لو بدك).
