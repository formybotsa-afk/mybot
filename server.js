const express = require('express');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const app = express();
app.use(express.json());

const PORT = process.env.PORT || 3000;
const BOT_PATH = path.join(__dirname, 'bot.py');
const TRIGGERS_PATH = path.join(__dirname, 'triggers.json');

// قراءة بيانات الحماية من .env
const DASHBOARD_USER = process.env.DASHBOARD_USER || 'admin';
const DASHBOARD_PASS = process.env.DASHBOARD_PASS || 'admin123456';

let botProcess = null;

// تشغيل البوت كعملية فرعية
function startBotProcess() {
    if (botProcess) {
        botProcess.kill();
    }
    console.log('🤖 جاري تشغيل بوت الديسكورد...');
    botProcess = spawn('python3', [BOT_PATH], { env: process.env });

    botProcess.stdout.on('data', (data) => console.log(`[Bot Output]: ${data}`));
    botProcess.stderr.on('data', (data) => console.error(`[Bot Error]: ${data}`));
    botProcess.on('close', (code) => console.log(`[Bot Exited] كود التوقف: ${code}`));
}

startBotProcess();

// إدارة الكلمات المفتاحية
function loadTriggers() {
    if (fs.existsSync(TRIGGERS_PATH)) {
        try {
            return JSON.parse(fs.readFileSync(TRIGGERS_PATH, 'utf8'));
        } catch (e) {}
    }
    return {};
}

function saveTriggers(data) {
    fs.writeFileSync(TRIGGERS_PATH, JSON.stringify(data, null, 2));
}

// 🔐 API تسجيل الدخول
app.post('/api/login', (req, res) => {
    const { username, password } = req.body;
    if (username === DASHBOARD_USER && password === DASHBOARD_PASS) {
        return res.json({ success: true });
    }
    res.status(401).json({ success: false, message: 'اسم المستخدم أو كلمة المرور غير صحيحة!' });
});

// --- API إدارة الكلمات والسكربتات ---

app.get('/api/triggers', (req, res) => {
    res.json(loadTriggers());
});

app.post('/api/triggers', (req, res) => {
    const { word, script } = req.body;
    if (!word || !script) return res.status(400).json({ error: 'الكلمة والسكربت مطلوبان' });

    const triggers = loadTriggers();
    triggers[word.toLowerCase().trim()] = script;
    saveTriggers(triggers);
    res.json({ success: true, message: `تم ربط الكلمة (${word}) بالسكربت بنجاح!` });
});

app.delete('/api/triggers/:word', (req, res) => {
    const triggers = loadTriggers();
    delete triggers[req.params.word.toLowerCase().trim()];
    saveTriggers(triggers);
    res.json({ success: true, message: 'تم حذف الكلمة' });
});

// --- API التحكم بكود البوت وتحديثه حياً ---

app.get('/api/bot-code', (req, res) => {
    try {
        const code = fs.readFileSync(BOT_PATH, 'utf8');
        res.json({ code });
    } catch (err) {
        res.status(500).json({ error: 'تعذر قراءة ملف الكود' });
    }
});

app.post('/api/bot-code', (req, res) => {
    try {
        const { code } = req.body;
        fs.writeFileSync(BOT_PATH, code, 'utf8');
        startBotProcess();
        res.json({ success: true, message: 'تم تحديث كود البوت وإعادة تشغيله حياً!' });
    } catch (err) {
        res.status(500).json({ error: 'فشل حفظ الكود' });
    }
});

app.post('/api/bot-restart', (req, res) => {
    startBotProcess();
    res.json({ success: true, message: 'تمت إعادة تشغيل البوت بنجاح!' });
});

// --- واجهة الويب الشاملة ---

app.get('/', (req, res) => {
    res.send(`
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>لوحة تحكم البوت الشاملة</title>
        <style>
            * { box-sizing: border-box; }
            body { font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }
            .container { max-width: 1000px; margin: 0 auto; }
            .card { background: #1e293b; padding: 25px; border-radius: 12px; margin-bottom: 20px; border: 1px solid #334155; shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); }
            h2 { color: #38bdf8; margin-top: 0; font-size: 1.4rem; }
            input, textarea { width: 100%; padding: 12px; background: #0f172a; border: 1px solid #334155; color: #38bdf8; border-radius: 8px; font-family: monospace; margin-bottom: 12px; }
            textarea { height: 280px; resize: vertical; }
            button { padding: 12px 20px; border: none; border-radius: 8px; cursor: pointer; font-weight: bold; background: #3b82f6; color: white; transition: 0.2s; }
            button:hover { opacity: 0.9; }
            .btn-danger { background: #ef4444; }
            .btn-success { background: #22c55e; }
            .btn-warning { background: #eab308; color: #000; }
            .trigger-item { display: flex; justify-content: space-between; align-items: center; background: #0f172a; padding: 12px; border-radius: 8px; margin-bottom: 10px; border: 1px solid #1e293b; }
            #loginSection { max-width: 400px; margin: 80px auto; text-align: center; }
            .hidden { display: none; }
            .badge { background: #0284c7; padding: 4px 8px; border-radius: 4px; font-size: 0.85rem; }
        </style>
    </head>
    <body>

        <!-- شاشة تسجيل الدخول -->
        <div id="loginSection" class="card">
            <h2>🔐 تسجيل الدخول للوحة التحكم</h2>
            <input type="text" id="loginUser" placeholder="اسم المستخدم">
            <input type="password" id="loginPass" placeholder="كلمة السر">
            <button class="btn-success" style="width:100%" onclick="login()">دخول</button>
        </div>

        <!-- لوحة التحكم الرئيسية -->
        <div id="dashboardSection" class="container hidden">
            <h1>⚙️ لوحة إدارة البوت والسكربتات بالكامل</h1>

            <!-- 1. قسم الكلمات المفتاحية والسكربتات -->
            <div class="card">
                <h2>🔗 ربط الكلمات بالسكربتات (مثل: لابوبو)</h2>
                <input type="text" id="triggerWord" placeholder="الكلمة المفتاحية (مثال: لابوبو)">
                <textarea id="triggerScript" placeholder="ضع السكربت الخاص بهذه الكلمة هنا..." style="height: 100px;"></textarea>
                <button class="btn-success" onclick="addTrigger()">➕ حفظ الكلمة والسكربت</button>

                <h3 style="margin-top:25px;">📋 قائمة الكلمات المفعّلة حالياً:</h3>
                <div id="triggersList"></div>
            </div>

            <!-- 2. قسم محرر الكود الحي للبوت -->
            <div class="card">
                <h2>📝 محرر كود البوت الحي (bot.py)</h2>
                <p style="color:#94a3b8; font-size: 0.9rem;">يمكنك تعديل كود البوت بالكامل من هنا وحفظه ليتم إعادة تشغيل البوت فوراً بالكود الجديد:</p>
                <textarea id="botCodeEditor" spellcheck="false"></textarea>
                <div style="display:flex; gap:10px;">
                    <button class="btn-success" onclick="saveBotCode()">💾 حفظ الكود وتشغيل البوت حياً</button>
                    <button class="btn-warning" onclick="restartBot()">🔄 إعادة تشغيل البوت</button>
                </div>
            </div>
        </div>

        <script>
            async function login() {
                const username = document.getElementById('loginUser').value;
                const password = document.getElementById('loginPass').value;

                const res = await fetch('/api/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ username, password })
                });

                const data = await res.json();
                if(data.success) {
                    document.getElementById('loginSection').classList.add('hidden');
                    document.getElementById('dashboardSection').classList.remove('hidden');
                    loadDashboardData();
                } else {
                    alert(data.message);
                }
            }

            async function loadDashboardData() {
                loadTriggers();
                loadBotCode();
            }

            async function loadTriggers() {
                const res = await fetch('/api/triggers');
                const data = await res.json();
                const list = document.getElementById('triggersList');
                list.innerHTML = '';

                if(Object.keys(data).length === 0) {
                    list.innerHTML = '<p style="color:#64748b;">لا توجد كلمات مربوطة حالياً.</p>';
                    return;
                }

                for (const [word, script] of Object.entries(data)) {
                    list.innerHTML += \`
                        <div class="trigger-item">
                            <div>
                                <span class="badge">\${word}</span>
                                <code style="margin-right:10px; color:#cbd5e1;">\${script.substring(0, 40)}...</code>
                            </div>
                            <button class="btn-danger" onclick="deleteTrigger('\${word}')">حذف</button>
                        </div>
                    \`;
                }
            }

            async function addTrigger() {
                const word = document.getElementById('triggerWord').value;
                const script = document.getElementById('triggerScript').value;
                if(!word || !script) return alert('يرجى كتابة الكلمة والسكربت!');

                const res = await fetch('/api/triggers', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ word, script })
                });
                const data = await res.json();
                alert(data.message);
                document.getElementById('triggerWord').value = '';
                document.getElementById('triggerScript').value = '';
                loadTriggers();
            }

            async function deleteTrigger(word) {
                if(!confirm(\`هل أنت أصل من حذف كلمة (\${word})؟\`)) return;
                await fetch('/api/triggers/' + encodeURIComponent(word), { method: 'DELETE' });
                loadTriggers();
            }

            async function loadBotCode() {
                const res = await fetch('/api/bot-code');
                const data = await res.json();
                document.getElementById('botCodeEditor').value = data.code || '';
            }

            async function saveBotCode() {
                const code = document.getElementById('botCodeEditor').value;
                const res = await fetch('/api/bot-code', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ code })
                });
                const data = await res.json();
                alert(data.message);
            }

            async function restartBot() {
                const res = await fetch('/api/bot-restart', { method: 'POST' });
                const data = await res.json();
                alert(data.message);
            }
        </script>
    </body>
    </html>
    `);
});

app.listen(PORT, () => console.log(`Server running on port ${PORT}`));
