import requests
import time
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)

# ================= 儲存從 D1 Mini 接收到的最新溫濕度 =================
sensor_data = {
    "temp": "--",
    "hum": "--"
}

# >>> 新增：按鈕冷卻設定（兩個按鈕共用）
COOLDOWN_SECONDS = 10
last_press_time = 0

# ================= 網頁前端介面 =================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>遠端控制與環境監控</title>
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            max-width: 600px;
            margin: 40px auto;
            padding: 20px;
            background-color: #f0f2f5;
            color: #333;
        }
        .card {
            background: white;
            padding: 25px;
            border-radius: 16px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.08);
            margin-bottom: 20px;
            text-align: center;
        }
        .btn-group {
            display: flex;
            gap: 15px;
            justify-content: center;
            margin-top: 15px;
        }
        .btn {
            flex: 1;
            padding: 14px 20px;
            font-size: 16px;
            font-weight: bold;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            color: white;
            transition: opacity 0.2s;
        }
        .btn:hover { opacity: 0.9; }
        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        .btn-orange { background-color: #f4511e; }
        .btn-dark-orange { background-color: #d84315; }
        .metric-value {
            font-size: 36px;
            font-weight: bold;
            color: #1976d2;
            margin: 10px 0;
        }
        .status-text {
            font-size: 14px;
            color: #666;
            margin-top: 10px;
        }
    </style>
</head>
<body>

    <div class="card">
        <h2>🖥️ 遠端電源控制台</h2>
        <h3>🔌 電源動作選擇</h3>
        <div class="btn-group">
            <button class="btn btn-orange" id="btn-on" onclick="triggerAction('power_on')">⚡ 開機 (點按1秒)</button>
            <button class="btn btn-dark-orange" id="btn-off" onclick="triggerAction('power_off')">⚠️ 強制關機 (點按5秒)</button>
        </div>
        <div class="status-text" id="action-status">準備就緒</div>
    </div>

    <div class="card">
        <h2>🌡️ 機櫃環境數據 (實時更新)</h2>
        <div style="display: flex; justify-content: space-around;">
            <div>
                <div>溫度</div>
                <div class="metric-value"><span id="temp">--</span> °C</div>
            </div>
            <div>
                <div>濕度</div>
                <div class="metric-value" style="color: #00897b;"><span id="hum">--</span> %</div>
            </div>
        </div>
    </div>

    <script>
        function updateSensor() {
            fetch('/api/status')
                .then(res => res.json())
                .then(data => {
                    document.getElementById('temp').innerText = data.temp;
                    document.getElementById('hum').innerText = data.hum;
                })
                .catch(err => console.error('抓取狀態失敗', err));
        }

        // >>> 新增：前端冷卻控制
        let cooldownUntil = 0;

        function startCooldown(seconds) {
            const btnOn = document.getElementById('btn-on');
            const btnOff = document.getElementById('btn-off');
            cooldownUntil = Date.now() + seconds * 1000;
            btnOn.disabled = true;
            btnOff.disabled = true;

            const origOn = '⚡ 開機 (點按1秒)';
            const origOff = '⚠️ 強制關機 (點按5秒)';
            let left = seconds;

            const timer = setInterval(() => {
                left--;
                if (left <= 0) {
                    clearInterval(timer);
                    btnOn.disabled = false;
                    btnOff.disabled = false;
                    btnOn.textContent = origOn;
                    btnOff.textContent = origOff;
                    cooldownUntil = 0;
                } else {
                    btnOn.textContent = `請等待 ${left} 秒`;
                    btnOff.textContent = `請等待 ${left} 秒`;
                }
            }, 1000);
        }

        function triggerAction(action) {
            // >>> 新增：前端先檢查冷卻
            if (Date.now() < cooldownUntil) {
                document.getElementById('action-status').innerText = '請等待冷卻結束';
                return;
            }

            document.getElementById('action-status').innerText = '執行中...';
            fetch('/api/control', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: action })
            })
            .then(async res => {
                const data = await res.json();
                // >>> 新增：處理 429 冷卻回應
                if (res.status === 429) {
                    document.getElementById('action-status').innerText = data.message;
                    startCooldown(Math.ceil(data.remaining));
                    return;
                }
                document.getElementById('action-status').innerText = data.message || '操作完成';
                startCooldown(10);
            })
            .catch(err => {
                document.getElementById('action-status').innerText = '通訊失敗';
            });
        }

        setInterval(updateSensor, 3000);
        updateSensor();
    </script>
</body>
</html>
"""

# ================= Flask 路由 =================
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/status')
def api_status():
    return jsonify({
        "temp": sensor_data["temp"],
        "hum": sensor_data["hum"]
    })

@app.route('/api/update', methods=['POST'])
def api_update():
    global sensor_data
    data = request.get_json() or {}
    if 'temp' in data and 'hum' in data:
        sensor_data["temp"] = data['temp']
        sensor_data["hum"] = data['hum']
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Invalid data"}), 400

@app.route('/api/control', methods=['POST'])
def api_control():
    # >>> 新增：後端冷卻檢查（防止繞過前端直接呼叫 API）
    global last_press_time
    now = time.time()
    elapsed = now - last_press_time
    if elapsed < COOLDOWN_SECONDS:
        remaining = round(COOLDOWN_SECONDS - elapsed, 1)
        return jsonify({
            'success': False,
            'status': 'cooldown',
            'remaining': remaining,
            'message': f'請等待 {remaining} 秒後再試'
        }), 429
    last_press_time = now

    data = request.get_json() or {}
    action = data.get('action')

    try:
        if action == 'power_on':
            requests.post("http://192.168.1.35/boot", json={"duration": 1000}, timeout=2)
            msg = "已發送開機指令 (1秒)"
        elif action == 'power_off':
            requests.post("http://192.168.1.35/boot", json={"duration": 5000}, timeout=2)
            msg = "已發送強制關機指令 (5秒)"
        else:
            return jsonify({'success': False, 'message': '未知指令'}), 400

        return jsonify({'success': True, 'message': msg})
    except Exception as e:
        return jsonify({'success': False, 'message': f'控制失敗: {str(e)}'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5080, debug=False)
