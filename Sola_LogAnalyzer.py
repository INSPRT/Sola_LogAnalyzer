import re
import urllib.parse
import requests
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)

# 1. 내 정보 설정 (여기에 너의 키를 꼭 넣어줘!)
CLIENT_ID = "a21fdf0d-4dc4-41bf-a9ed-b0df28c97b8c"
CLIENT_SECRET = "W8uWpREXlYsdLoGge7ZHGFE6jupPLIKiqiT0vlXh"

CLASS_INFO = {
    "DeathKnight": {"kr": "죽음의 기사", "color": "#C41E3A", "class": "text-[#C41E3A]"},
    "DemonHunter": {"kr": "악마사냥꾼", "color": "#A330C9", "class": "text-[#A330C9]"},
    "Druid": {"kr": "드루이드", "color": "#FF7C0A", "class": "text-[#FF7C0A]"},
    "Evoker": {"kr": "기원사", "color": "#33937F", "class": "text-[#33937F]"},
    "Hunter": {"kr": "사냥꾼", "color": "#AAD372", "class": "text-[#AAD372]"},
    "Mage": {"kr": "마법사", "color": "#3FC7EB", "class": "text-[#3FC7EB]"},
    "Monk": {"kr": "수도사", "color": "#00FF98", "class": "text-[#00FF98]"},
    "Paladin": {"kr": "성기사", "color": "#F48CBA", "class": "text-[#F48CBA]"},
    "Priest": {"kr": "사제", "color": "#FFFFFF", "class": "text-white"},
    "Rogue": {"kr": "도적", "color": "#FFF468", "class": "text-[#FFF468]"},
    "Shaman": {"kr": "주술사", "color": "#0070DE", "class": "text-[#0070DE]"},
    "Warlock": {"kr": "흑마법사", "color": "#8788EE", "class": "text-[#8788EE]"},
    "Warrior": {"kr": "전사", "color": "#C69B6D", "class": "text-[#C69B6D]"},
}

def get_access_token():
    url = "https://www.warcraftlogs.com/oauth/token"
    data = {"grant_type": "client_credentials", "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}
    try:
        response = requests.post(url, data=data, timeout=10)
        return response.json().get("access_token") if response.status_code == 200 else None
    except Exception as e:
        print(f"[오류] 토큰 발급 실패: {e}")
        return None

def parse_wcl_url(raw_url):
    match = re.search(r'(?:reports/|code=)([a-zA-Z0-9]{16})', raw_url)
    report_code = match.group(1) if match else None
    if not report_code:
        clean_str = raw_url.strip()
        if re.match(r'^[a-zA-Z0-9]{16}$', clean_str):
            report_code = clean_str
    
    if not report_code:
        return None
        
    parsed_url = urllib.parse.urlparse(raw_url)
    qs = urllib.parse.parse_qs(parsed_url.query)
    boss = qs.get('boss', [None])[0]
    
    return {
        "report_code": report_code,
        "boss": boss
    }

def calculate_robust_slope(y_values):
    """
    [WEFT 4.0 (Weighted Error Frequency & Recency Trend 4.0)]
    공대장의 핵심 철학 및 합리성 완벽 반영:
    1. 사망 횟수(실책 빈도)가 많은 사람은 그 어떤 추세 보정이 있더라도 사망 횟수가 적은 시점보다 무조건 점수가 낮아야 한다 (역전 불가 원칙).
    2. 선형 회귀의 왜곡(2번 죽고 2번 살았다고 우상향 추세라며 페널티를 대폭 깎아주는 현상)을 완전 제거.
    3. 사망 시점(과거 vs 최근)은 동일 사망 횟수 내에서만 작용하는 보조 가중치(최대 40% 스윙)로 작동.
    """
    M = len(y_values)
    if M == 0:
        return None
    
    # 99.5 미만인 경우를 실패(사망)로 간주하고 실패한 인덱스를 추출
    failures = [i for i, y in enumerate(y_values) if y < 99.5]
    failure_count = len(failures)
    
    # 100% 완벽 생존자
    if failure_count == 0:
        return 0.0
        
    failure_rate = (failure_count / M) * 100.0
    
    # 사망 횟수(비율)에 따른 확고한 기본 감점 티어
    base_penalty = ((failure_rate / 20.0) ** 1.35) * 7.0
    
    # 최근 사망 시점 가중치 계산 (oldest = -1.0, middle = 0.0, newest = +1.0)
    if M > 1:
        mid_idx = (M - 1) / 2.0
        pos_values = [(i - mid_idx) / mid_idx for i in failures]
        avg_pos = sum(pos_values) / failure_count
    else:
        avg_pos = 0.0
        
    # 동일 데스 티어 내에서 최근 사망일수록 감점 강화, 과거 사망일수록 감점 완화 (최대 40% 스윙)
    swing = base_penalty * 0.4 * avg_pos
    final_penalty = base_penalty + swing
    
    return -final_penalty

def get_condition_info(y_values, valid_death_rate=0.0):
    """
    [WEFT 4.0 상대적 베이스라인 보정 및 직관적 티어제]
    - 완벽 생존자(0회 사망)의 경우 과거 트라이 이력을 비교하여 진성 에이스(Perfect)와 극복 각성자(+N%)로 스마트 분기
    - 사망자의 경우 음수 수치에 따라 트롤💀, 심각⚠️, 주의⚡ 3단계로 직관적 분류
    """
    slope = calculate_robust_slope(y_values)
    if slope is None:
        return {"badge": "⚠️", "text": "데이터<br>부족", "class": "bg-gray-500/20 text-gray-400 border-gray-500/30", "order": 0}
    
    # 1. 최근 M회 중 단 한 번도 사망하지 않은 완벽 생존자 (slope == 0.0)
    if slope == 0.0:
        if valid_death_rate < 5.0:
            # 전체 트라이에서도 사망률 5% 미만인 순수 에이스
            return {"badge": "🌟", "text": "최상<br>Perfect", "class": "bg-emerald-500/20 text-emerald-400 border-emerald-500/30 font-extrabold", "order": 5}
        else:
            # 과거에 사망 이력이 있으나 최근 완벽하게 극복한 각성자
            return {"badge": "📈", "text": f"상승<br>+{valid_death_rate:.1f}%", "class": "bg-sky-500/20 text-sky-400 border-sky-500/30 font-bold", "order": 4}
            
    # 2. 최근 M회 중 사망자가 발생한 경우 (slope < 0.0)
    if slope <= -14.0:
        return {"badge": "💀", "text": f"트롤<br>{slope:.1f}%", "class": "bg-rose-500/20 text-rose-400 border-rose-500/30 font-extrabold animate-pulse", "order": 1}
    elif slope <= -7.0:
        return {"badge": "⚠️", "text": f"심각<br>{slope:.1f}%", "class": "bg-orange-500/20 text-orange-400 border-orange-500/30 font-bold", "order": 2}
    else:
        return {"badge": "⚡", "text": f"주의<br>{slope:.1f}%", "class": "bg-amber-500/20 text-amber-400 border-amber-500/30 font-semibold", "order": 3}

def build_tooltip_html(details_list, count):
    if not details_list or len(details_list) < count:
        return f"""
        <div class="condition-tooltip absolute bottom-full right-0 mb-2 hidden group-hover:block group-[.pinned]:block w-64 p-4 bg-gray-900/95 border border-gray-700/80 rounded-2xl shadow-2xl backdrop-blur-xl text-left text-xs z-50 text-gray-300">
            ⚠️ 분석에 필요한 최소 트라이 횟수({count}회)가 부족합니다.
        </div>
        """
    
    recent_details = details_list[-count:]
    
    items_html = ""
    for item in recent_details:
        f_num = item["fight_num"]
        survived = item["survived"]
        rate = item["rate"]
        label = item["label"]
        
        if survived:
            status_badge = '<span class="text-emerald-400 font-bold">🛡️ 생존 (100%)</span>'
            desc = '<span class="text-gray-400 text-[11px]">전멸 전 유효 생존</span>'
        else:
            status_badge = f'<span class="text-rose-400 font-bold">💥 사망 (Active: {rate:.1f}%)</span>'
            desc = f'<span class="text-amber-300 font-semibold text-[11px]">{label}</span>'
            
        items_html += f"""
        <div class="flex items-center justify-between bg-gray-800/60 p-2 rounded-xl border border-gray-700/50 hover:bg-gray-800 transition-all">
            <span class="font-bold text-indigo-300 w-16 shrink-0">{f_num}트라이:</span>
            <div class="flex flex-col text-right">
                <div>{status_badge}</div>
                <div>{desc}</div>
            </div>
        </div>
        """
        
    return f"""
    <div class="condition-tooltip absolute bottom-full right-0 mb-2 hidden group-hover:block group-[.pinned]:block w-72 p-4 bg-gray-900/98 border border-gray-700 rounded-2xl shadow-2xl backdrop-blur-xl text-left text-xs z-50 transition-all duration-200 text-gray-200 space-y-2.5">
        <div class="font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-indigo-300 to-rose-300 border-b border-gray-700 pb-1.5 flex items-center justify-between">
            <span>📋 최근 {count}회 사망/생존 분석</span>
            <span class="text-[10px] bg-indigo-500/20 text-indigo-300 px-2 py-0.5 rounded-full border border-indigo-500/30">WEFT 4.0</span>
        </div>
        <div class="space-y-1.5 max-h-64 overflow-y-auto pr-1">
            {items_html}
        </div>
    </div>
    """

def get_parsed_data(report_code, boss_param=None):
    token = get_access_token()
    if not token: return {"error": "API 토큰 발급에 실패했습니다."}

    url = "https://www.warcraftlogs.com/api/v2/client"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    query = """
    query ($code: String!) {
      reportData {
        report(code: $code) {
          title
          playerDetails(endTime: 9999999999999)
          masterData { actors(type: "Player") { id name subType } }
          fights(killType: Encounters) { id name startTime endTime encounterID kill friendlyPlayers }
          events(dataType: Deaths, startTime: 0, endTime: 9999999999999, limit: 10000) { data }
        }
      }
    }
    """
    try:
        raw_data = requests.post(url, headers=headers, json={"query": query, "variables": {"code": report_code}}, timeout=15).json()
    except Exception as e:
        print(f"[오류] API 요청 실패: {e}")
        return {"error": f"Warcraft Logs API 요청 중 오류가 발생했습니다: {e}"}

    report = raw_data.get("data", {}).get("reportData", {}).get("report")
    if not report: 
        print(f"[오류] GraphQL API 에러 응답: {raw_data}")
        return {"error": "리포트 데이터를 찾을 수 없습니다. 코드를 확인해 주세요."}

    report_title = report.get("title", "Warcraft Logs 리포트")
    raw_fights = report.get("fights", [])
    death_events = report.get("events", {}).get("data", [])
    
    if not raw_fights: return {"error": "리포트 내에 전투(Encounters) 기록이 없습니다."}

    fights = []
    boss_name = "전체 보스"
    active_player_ids = set()

    for f in raw_fights:
        if boss_param and boss_param != '0':
            if str(f.get('encounterID')) != str(boss_param):
                continue
            if boss_name == "전체 보스" and f.get('name'):
                boss_name = f.get('name')
        
        f_start = f.get("startTime", 0)
        f_end = f.get("endTime", 0)
        if (f_end - f_start) < 20000:  # 20초 미만 리셋 풀 제외
            continue
        
        fights.append(f)
        for p_id in f.get("friendlyPlayers", []):
            active_player_ids.add(p_id)

    filter_summary = f"{boss_name} | 전체 트라이 (20초 이상)"

    total_fights = len(fights)
    if total_fights == 0:
        return {"error": f"선택하신 필터 조건({filter_summary})에 부합하는 전투 데이터가 없습니다."}

    all_actors = report.get("masterData", {}).get("actors", [])
    if active_player_ids:
        players = {actor["id"]: {"name": actor["name"], "class": actor.get("subType", "Unknown"), "role": "딜러"} for actor in all_actors if actor["id"] in active_player_ids}
    else:
        players = {actor["id"]: {"name": actor["name"], "class": actor.get("subType", "Unknown"), "role": "딜러"} for actor in all_actors}

    p_details = report.get("playerDetails")
    if isinstance(p_details, dict) and "data" in p_details: p_details = p_details["data"]
    if isinstance(p_details, dict) and "playerDetails" in p_details: p_details = p_details["playerDetails"]
    
    if isinstance(p_details, dict):
        for role_key, role_name in [("tanks", "탱커"), ("healers", "힐러"), ("dps", "딜러")]:
            for p in p_details.get(role_key, []):
                p_id = p.get("id")
                if p_id in players:
                    players[p_id]["role"] = role_name
                    if p.get("type"): players[p_id]["class"] = p.get("type")

    stats = {
        p_info["name"]: {
            "name": p_info["name"],
            "class": p_info["class"],
            "role": p_info["role"],
            "valid_deaths": 0,
            "first_deaths": 0,
            "second_deaths": 0,
            "third_deaths": 0,
            "solo_blunders": 0,
            "death_orders": [],
            "effective_times": [],
            "max_effective_times": [],
            "effective_rates": [],
            "fight_details": [],
            "raw_survival_rates": [],
            "survived_fights": 0,
            "total_raw_deaths": 0
        } for p_info in players.values()
    }

    total_p_count = len(players) if len(players) > 0 else 20

    for f_idx, fight in enumerate(fights, 1):
        f_id, f_start, f_end = fight["id"], fight["startTime"], fight["endTime"]
        fight_deaths = sorted([e for e in death_events if e.get("fight") == f_id], key=lambda x: x["timestamp"])
        
        unique_deaths = []
        seen_players = set()
        for d in fight_deaths:
            p_info = players.get(d.get("targetID"))
            if not p_info: continue
            p_name = p_info["name"]
            if p_name in seen_players: continue
            seen_players.add(p_name)
            unique_deaths.append((p_name, d["timestamp"], d))
        
        t_collapse = f_end
        for i, (p_name, t_i, d) in enumerate(unique_deaths):
            collapse_count = sum(1 for _, t_j, _ in unique_deaths[i:] if t_i <= t_j <= t_i + 10000)
            alive_before = total_p_count - i
            threshold = max(4, alive_before * 0.5)
            if collapse_count >= threshold:
                t_collapse = t_i - 1
                break
        
        fight_max_time = (t_collapse - f_start) / 1000.0
        if fight_max_time <= 0: fight_max_time = 1.0
        
        fight_total_duration = (f_end - f_start) / 1000.0
        if fight_total_duration <= 0: fight_total_duration = 1.0
        dead_p_map = {p: t for p, t, _ in unique_deaths}
        for p_name in stats.keys():
            if p_name in dead_p_map:
                raw_sec = (dead_p_map[p_name] - f_start) / 1000.0
                stats[p_name]["raw_survival_rates"].append(max(0.0, min(100.0, (raw_sec / fight_total_duration) * 100.0)))
            else:
                stats[p_name]["raw_survival_rates"].append(100.0)

        valid_deaths = []
        for idx, (p, t, d) in enumerate(unique_deaths):
            if t > t_collapse: break
            if idx >= 3: break
            valid_deaths.append((p, t, d))

        dead_in_this_fight_validly = set()
        for idx, (p_name, t_death, d) in enumerate(valid_deaths):
            dead_in_this_fight_validly.add(p_name)
            stats[p_name]["valid_deaths"] += 1
            stats[p_name]["total_raw_deaths"] += 1
            stats[p_name]["death_orders"].append(idx + 1)
            
            survival_sec = (t_death - f_start) / 1000.0
            stats[p_name]["effective_times"].append(max(0.0, survival_sec))
            stats[p_name]["max_effective_times"].append(fight_max_time)
            
            eff_rate = (survival_sec / fight_max_time) * 100.0 if fight_max_time > 0 else 0.0
            stats[p_name]["effective_rates"].append(max(0.0, min(100.0, eff_rate)))

            if idx == 0: stats[p_name]["first_deaths"] += 1
            elif idx == 1: stats[p_name]["second_deaths"] += 1
            elif idx == 2: stats[p_name]["third_deaths"] += 1

            death_label = f"{idx+1}번째 사망"
            neighbors = [other_p for other_idx, (other_p, other_t, _) in enumerate(valid_deaths) if other_idx != idx and abs(other_t - t_death) <= 5000]
            if not neighbors:
                stats[p_name]["solo_blunders"] += 1
                death_label += " 💀단독사망"

            stats[p_name]["fight_details"].append({
                "fight_num": f_idx,
                "survived": False,
                "rate": eff_rate,
                "label": death_label
            })

        for p_name in stats.keys():
            if p_name not in dead_in_this_fight_validly:
                stats[p_name]["survived_fights"] += 1
                stats[p_name]["effective_times"].append(fight_max_time)
                stats[p_name]["max_effective_times"].append(fight_max_time)
                stats[p_name]["effective_rates"].append(100.0)
                stats[p_name]["fight_details"].append({
                    "fight_num": f_idx,
                    "survived": True,
                    "rate": 100.0,
                    "label": "생존 (또는 전멸 이후 사망)"
                })
                if p_name in dead_p_map:
                    stats[p_name]["total_raw_deaths"] += 1

    result_list = []
    most_first_deaths = {"name": "없음", "count": 0, "class_color_class": "text-white"}
    most_solo_blunders = {"name": "없음", "count": 0, "class_color_class": "text-white"}

    for name, data in stats.items():
        if data["total_raw_deaths"] == 0 and data["survived_fights"] == 0: continue
        
        sum_eff = sum(data["effective_times"])
        sum_max = sum(data["max_effective_times"])
        survival_rate = (sum_eff / sum_max * 100.0) if sum_max > 0 else 100.0
        avg_time = sum_eff / total_fights if total_fights > 0 else 0

        top2_count = data["first_deaths"] + data["second_deaths"]
        top2_ratio = (top2_count / total_fights) * 100.0 if total_fights > 0 else 0.0
        
        first_penalty = (data["first_deaths"] * 5.0) + ((data["first_deaths"] / total_fights) * 40.0)
        second_penalty = (data["second_deaths"] * 3.0) + ((data["second_deaths"] / total_fights) * 20.0)
        third_penalty = (data["third_deaths"] * 1.5) + ((data["third_deaths"] / total_fights) * 10.0)
        solo_penalty = (data["solo_blunders"] * 4.0) + ((data["solo_blunders"] / total_fights) * 30.0)
        time_penalty = (1.0 - (sum_eff / sum_max if sum_max > 0 else 1.0)) * 100.0
        bonus = (data["survived_fights"] / total_fights) * 5.0
        
        raw_score = 100.0 - first_penalty - second_penalty - third_penalty - solo_penalty - time_penalty + bonus
        score = max(0.0, min(100.0, raw_score))

        p_class_norm = data["class"].replace(" ", "")
        c_info = CLASS_INFO.get(p_class_norm, {"kr": data["class"], "color": "#FFFFFF", "class": "text-white"})

        if data["first_deaths"] > most_first_deaths["count"]:
            most_first_deaths = {"name": name, "count": data["first_deaths"], "class_color_class": c_info["class"]}
        if data["solo_blunders"] > most_solo_blunders["count"]:
            most_solo_blunders = {"name": name, "count": data["solo_blunders"], "class_color_class": c_info["class"]}

        eff_rates = data["effective_rates"]
        fight_details = data["fight_details"]

        valid_death_rate = (data["valid_deaths"] / total_fights) * 100.0 if total_fights > 0 else 0.0

        # 공대장 요청 반영: 분석 범위 10/7(기본)/5/3회 선택지 제공, WEFT 4.0 적용
        cond_recent10 = get_condition_info(eff_rates[-10:], valid_death_rate) if len(eff_rates) >= 10 else {"badge": "⚠️", "text": "최소 10회<br>필요", "class": "bg-gray-500/20 text-gray-400 border-gray-500/30", "order": 0}
        cond_recent7 = get_condition_info(eff_rates[-7:], valid_death_rate) if len(eff_rates) >= 7 else {"badge": "⚠️", "text": "최소 7회<br>필요", "class": "bg-gray-500/20 text-gray-400 border-gray-500/30", "order": 0}
        cond_recent5 = get_condition_info(eff_rates[-5:], valid_death_rate) if len(eff_rates) >= 5 else {"badge": "⚠️", "text": "최소 5회<br>필요", "class": "bg-gray-500/20 text-gray-400 border-gray-500/30", "order": 0}
        cond_recent3 = get_condition_info(eff_rates[-3:], valid_death_rate) if len(eff_rates) >= 3 else {"badge": "⚠️", "text": "최소 3회<br>필요", "class": "bg-gray-500/20 text-gray-400 border-gray-500/30", "order": 0}

        tooltip_recent10 = build_tooltip_html(fight_details, 10)
        tooltip_recent7 = build_tooltip_html(fight_details, 7)
        tooltip_recent5 = build_tooltip_html(fight_details, 5)
        tooltip_recent3 = build_tooltip_html(fight_details, 3)

        result_list.append({
            "name": name,
            "class_kr": c_info["kr"],
            "class_color_class": c_info["class"],
            "first_deaths": data["first_deaths"], 
            "second_deaths": data["second_deaths"], 
            "third_deaths": data["third_deaths"], 
            "solo_blunders": data["solo_blunders"],
            "top2_ratio": f"{top2_ratio:.1f}%",
            "top2_ratio_num": round(top2_ratio, 1), 
            "survival_rate": f"{survival_rate:.1f}%",
            "survival_rate_num": round(survival_rate, 1), 
            "avg_time": f"{avg_time:.1f}초", 
            "avg_time_num": round(avg_time, 1), 
            "score": round(score, 1),
            "condition_recent10": cond_recent10,
            "condition_recent7": cond_recent7,
            "condition_recent5": cond_recent5,
            "condition_recent3": cond_recent3,
            "tooltip_recent10": tooltip_recent10,
            "tooltip_recent7": tooltip_recent7,
            "tooltip_recent5": tooltip_recent5,
            "tooltip_recent3": tooltip_recent3
        })

    return {
        "report_title": report_title,
        "report_code": report_code,
        "filter_summary": filter_summary,
        "total_fights": total_fights, 
        "players": result_list,
        "most_first_deaths": most_first_deaths,
        "most_solo_blunders": most_solo_blunders,
        "total_players_count": len(result_list)
    }

LANDING_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Warcraft Logs 생존력 분석 도구</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=Outfit:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
        body { background-color: #0b0f19; color: #f3f4f6; font-family: 'Inter', sans-serif; }
    </style>
</head>
<body class="min-h-screen flex items-center justify-center p-6 relative overflow-hidden">
    <!-- Background Glow Effects -->
    <div class="absolute top-10 left-1/4 w-96 h-96 bg-indigo-500/15 rounded-full blur-3xl pointer-events-none -z-10"></div>
    <div class="absolute bottom-10 right-1/4 w-96 h-96 bg-rose-500/15 rounded-full blur-3xl pointer-events-none -z-10"></div>

    <div class="max-w-3xl w-full mx-auto">
        <!-- Input Section -->
        <div id="inputSection" class="bg-gray-900/60 border border-gray-800 rounded-3xl p-8 md:p-12 shadow-2xl backdrop-blur-2xl text-center">
            {% if error %}
            <div class="mb-6 p-4 bg-rose-500/20 border border-rose-500/40 text-rose-300 rounded-2xl text-sm font-semibold shadow-lg">
                ⚠️ {{ error }}
            </div>
            {% endif %}
            <div class="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 text-sm font-semibold mb-6">
                ✨ 올바른 사망률 데이터 분석 도구
            </div>
            <h1 class="text-4xl md:text-5xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-indigo-300 via-purple-300 to-rose-300 font-outfit tracking-tight mb-4">
                Warcraft Logs 생존력 분석 도구
            </h1>
            <p class="text-gray-400 text-base mb-8 max-w-xl mx-auto">
                로그 주소를 붙여넣으면 해당 로그의 전체 트라이를 종합적으로 분석하여 공대의 트라이 횟수를 늘리는 '진짜 범인'을 찾아냅니다.
            </p>

            <form onsubmit="startAnalysis(event)" class="space-y-4">
                <div class="relative">
                    <input id="logUrl" type="text" placeholder="https://ko.warcraftlogs.com/reports/aT2hxt1CgB8fPN6p?boss=3181..." 
                        class="w-full px-6 py-4 rounded-2xl bg-gray-800/80 border border-gray-700 text-white placeholder-gray-500 focus:outline-none focus:border-indigo-500 text-base shadow-inner transition-all">
                </div>
                <button type="submit" 
                    class="w-full py-4 rounded-2xl bg-gradient-to-r from-indigo-600 to-rose-600 hover:from-indigo-500 hover:to-rose-500 text-white font-bold text-lg shadow-lg hover:shadow-indigo-500/25 transition-all duration-200 active:scale-[0.98]">
                    데이터 분석 시작 🚀
                </button>
            </form>

            <div class="mt-8 text-xs text-gray-500 border-t border-gray-800/80 pt-6 space-y-2 text-left bg-gray-950/40 p-4 rounded-xl">
                <div class="font-bold text-gray-400">💡 입력 가능 URL 예시:</div>
                <p>• <span class="text-gray-400">특정 보스 전체 트라이</span>: https://ko.warcraftlogs.com/reports/aT2hxt1CgB8fPN6p?type=summary&boss=3181&difficulty=5&wipes=1</p>
                <p>• <span class="text-gray-400">리포트 전체</span>: https://ko.warcraftlogs.com/reports/aT2hxt1CgB8fPN6p</p>
                <p>• <span class="text-gray-400">리포트 코드</span>: aT2hxt1CgB8fPN6p</p>
            </div>
        </div>

        <!-- Loading Section (Hidden initially) -->
        <div id="loadingSection" class="bg-gray-900/60 border border-gray-800 rounded-3xl p-8 md:p-12 shadow-2xl backdrop-blur-2xl text-center" style="display: none;">
            <div class="mb-8 inline-block">
                <div class="relative w-24 h-24">
                    <div class="absolute inset-0 rounded-full border-4 border-gray-800"></div>
                    <div class="absolute inset-0 rounded-full border-4 border-indigo-500 border-t-transparent animate-spin"></div>
                    <div class="absolute inset-2 rounded-full border-4 border-rose-500 border-b-transparent animate-spin duration-700"></div>
                </div>
            </div>

            <h2 class="text-3xl font-extrabold text-white font-outfit mb-3">
                데이터 집계 및 생존 점수 계산 중...
            </h2>
            <p id="statusText" class="text-indigo-300 font-medium text-base mb-8 h-6 animate-pulse">
                🔗 Warcraft Logs GraphQL API 서버 연결 중...
            </p>

            <!-- Progress Bar -->
            <div class="max-w-md mx-auto bg-gray-800 rounded-full h-4 overflow-hidden p-1 border border-gray-700 mb-3 shadow-inner">
                <div id="progressBar" class="bg-gradient-to-r from-indigo-500 via-purple-500 to-rose-500 h-full rounded-full transition-all duration-300 ease-out" style="width: 0%;"></div>
            </div>
            <div id="progressText" class="text-sm font-bold text-gray-400 font-outfit">0%</div>
        </div>
    </div>

    <script>
        function startAnalysis(event) {
            event.preventDefault();
            const urlInput = document.getElementById('logUrl').value.trim();
            if (!urlInput) {
                alert('Warcraft Logs URL 또는 리포트 코드를 입력해 주세요.');
                return;
            }

            document.getElementById('inputSection').style.display = 'none';
            document.getElementById('loadingSection').style.display = 'block';

            const progressBar = document.getElementById('progressBar');
            const progressText = document.getElementById('progressText');
            const statusText = document.getElementById('statusText');

            const messages = [
                { percent: 0, text: "🔗 Warcraft Logs GraphQL API 서버 연결 중..." },
                { percent: 20, text: "📥 레이드 전투(Fights) 및 전체 사망(Deaths) 이벤트 파싱 중..." },
                { percent: 50, text: "🛡️ 고의 전멸 필터 작동 중 (누적 3인 데스 & 10초 붕괴 감지)..." },
                { percent: 80, text: "🤖 AI 생존 점수 산출 및 실책 빈도 가중 회귀 분석 중..." },
                { percent: 95, text: "⏳ 분석이 거의 완료되었습니다. 최종 데이터를 생성 중입니다..." }
            ];

            let currentPercent = 0;
            let messageIndex = 0;

            const interval = setInterval(() => {
                if (currentPercent < 95) {
                    currentPercent += 1;
                    progressBar.style.width = currentPercent + '%';
                    progressText.innerText = currentPercent + '%';

                    if (messageIndex < messages.length - 1 && currentPercent >= messages[messageIndex + 1].percent) {
                        messageIndex++;
                        statusText.innerText = messages[messageIndex].text;
                    }
                }
            }, 80);

            fetch('/api/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: urlInput })
            })
            .then(response => {
                if (!response.ok) {
                    return response.text().then(errText => { throw new Error(errText); });
                }
                return response.text();
            })
            .then(html => {
                clearInterval(interval);
                progressBar.style.width = '100%';
                progressText.innerText = '100%';
                statusText.innerText = "🎉 분석 완료! 대시보드를 렌더링합니다...";

                // 새로고침(F5) 시 유지되도록 URL 주소창 변경
                window.history.pushState({ url: urlInput }, "", "/?url=" + encodeURIComponent(urlInput));

                setTimeout(() => {
                    document.open();
                    document.write(html);
                    document.close();
                }, 600);
            })
            .catch(error => {
                clearInterval(interval);
                alert('⚠️ ' + error.message);
                document.getElementById('inputSection').style.display = 'block';
                document.getElementById('loadingSection').style.display = 'none';
            });
        }
    </script>
</body>
</html>
"""

REPORT_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ data.report_title }} - 공대 생존력 및 진짜 범인 분석 리포트</title>
    <!-- Tailwind CSS -->
    <script src="https://cdn.tailwindcss.com"></script>
    <!-- Google Fonts -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=Outfit:wght@400;600;700;800&display=swap" rel="stylesheet">
    <!-- DataTables CSS -->
    <link rel="stylesheet" type="text/css" href="https://cdn.datatables.net/1.13.6/css/jquery.dataTables.css">
    <!-- jQuery & DataTables JS -->
    <script type="text/javascript" charset="utf-8" src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    <script type="text/javascript" charset="utf-8" src="https://cdn.datatables.net/1.13.6/js/jquery.dataTables.js"></script>
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    fontFamily: {
                        sans: ['Inter', 'sans-serif'],
                        outfit: ['Outfit', 'sans-serif'],
                    },
                    colors: {
                        darkbg: '#0b0f19',
                        cardbg: '#111827',
                        tablebg: '#1f2937',
                    }
                }
            }
        }
    </script>
    <style>
        body { background-color: #0b0f19; color: #f3f4f6; font-family: 'Inter', sans-serif; }
        /* DataTables Custom Override */
        .dataTables_wrapper .dataTables_length, .dataTables_wrapper .dataTables_filter, 
        .dataTables_wrapper .dataTables_info, .dataTables_wrapper .dataTables_paginate { color: #9ca3af !important; font-size: 0.875rem; margin-bottom: 1rem; }
        .dataTables_wrapper .dataTables_filter input { background-color: #1f2937 !important; color: white !important; border: 1px solid #374151 !important; padding: 6px 12px; border-radius: 6px; outline: none; margin-left: 8px; transition: border-color 0.2s; }
        .dataTables_wrapper .dataTables_filter input:focus { border-color: #6366f1 !important; }
        table.dataTable { border-collapse: collapse !important; border-bottom: none !important; }
        table.dataTable thead th { border-bottom: 1px solid #374151 !important; font-weight: 600; color: #a5b4fc; padding: 12px 16px; transition: background-color 0.2s; }
        table.dataTable tbody tr { background-color: #111827 !important; color: #e5e7eb !important; transition: all 0.2s ease; }
        table.dataTable tbody tr:hover { background-color: #1f2937 !important; transform: scale(1.002); }
        table.dataTable tbody td { border-bottom: 1px solid #1f2937 !important; padding: 14px 16px; }
        
        /* ⭐ 정렬된 열(Column) 하이라이트 커스텀 스타일 (고급 인디고 틴트) */
        table.dataTable tbody td.sorting_1 { background-color: #1e1b4b !important; font-weight: 600; }
        table.dataTable tbody tr:hover td.sorting_1 { background-color: #312e81 !important; }
        table.dataTable thead th.sorting_asc, table.dataTable thead th.sorting_desc { background-color: #312e81 !important; color: #c7d2fe !important; }

        .dataTables_wrapper .dataTables_paginate .paginate_button { color: #e5e7eb !important; background: #1f2937 !important; border: 1px solid #374151 !important; border-radius: 6px; padding: 6px 12px; margin: 0 4px; }
        .dataTables_wrapper .dataTables_paginate .paginate_button.current { background: #6366f1 !important; color: white !important; border-color: #6366f1 !important; }
        .dataTables_wrapper .dataTables_paginate .paginate_button:hover { background: #4f46e5 !important; color: white !important; border-color: #4f46e5 !important; }
    </style>
</head>
<body class="min-h-screen p-6 md:p-12 relative overflow-x-hidden">
    <!-- Background Glow Effects -->
    <div class="absolute top-0 left-1/4 w-96 h-96 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none -z-10"></div>
    <div class="absolute top-1/3 right-10 w-96 h-96 bg-rose-500/10 rounded-full blur-3xl pointer-events-none -z-10"></div>
    <div class="absolute bottom-10 left-1/3 w-96 h-96 bg-emerald-500/10 rounded-full blur-3xl pointer-events-none -z-10"></div>

    <div class="max-w-7xl mx-auto">
        <!-- Back Button & Header / Hero Section -->
        <div class="mb-8 flex flex-col md:flex-row items-center justify-between gap-4 border-b border-gray-800/80 pb-6">
            <a href="/" class="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-gray-800 border border-gray-700 text-gray-300 hover:text-white hover:bg-gray-700 transition-all font-semibold text-sm shadow-md">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 19l-7-7m0 0l7-7m-7 7h18"></path></svg>
                ← 다른 로그 분석하기
            </a>
            <div class="flex flex-wrap gap-2 items-center">
                <div class="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 text-xs font-semibold backdrop-blur-md">
                    <span>리포트 코드: {{ data.report_code }}</span>
                </div>
                <div class="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-amber-500/10 border border-amber-500/20 text-amber-400 text-xs font-semibold backdrop-blur-md">
                    <span>🎯 필터 조건: {{ data.filter_summary }}</span>
                </div>
            </div>
        </div>

        <header class="text-center mb-12">
            <h1 class="text-3xl md:text-5xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-indigo-300 via-purple-300 to-rose-300 font-outfit tracking-tight mb-3">
                {{ data.report_title }}
            </h1>
            <p class="text-gray-400 text-sm max-w-2xl mx-auto">
                공대장의 전멸 지시를 감지하는 필터링 로직 적용됨. 신뢰도 높은 데이터 범위를 스마트하게 골라내어 공대의 트라이를 방해하는 진짜 범인을 알아볼까요?
            </p>
        </header>

        <!-- Summary Metric Cards (Hero Section) -->
        <div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-10">
            <div class="bg-cardbg border border-gray-800 rounded-2xl p-6 shadow-xl backdrop-blur-xl hover:border-gray-700 transition-all flex flex-col justify-between h-full">
                <div>
                    <div class="flex items-center justify-between mb-3">
                        <span class="text-gray-400 font-medium text-sm">총 트라이 횟수</span>
                        <span class="p-2 bg-indigo-500/10 text-indigo-400 rounded-lg">🎯</span>
                    </div>
                    <div class="text-4xl font-extrabold font-outfit text-white flex items-baseline gap-1.5">
                        {{ data.total_fights }} <span class="text-xl font-semibold text-gray-400">Tries</span>
                    </div>
                </div>
                <div class="text-xs text-transparent mt-2 pointer-events-none select-none">spacer</div>
            </div>

            <div class="bg-cardbg border border-gray-800 rounded-2xl p-6 shadow-xl backdrop-blur-xl hover:border-gray-700 transition-all flex flex-col justify-between h-full">
                <div>
                    <div class="flex items-center justify-between mb-3">
                        <span class="text-gray-400 font-medium text-sm">분석 대상 공대원</span>
                        <span class="p-2 bg-purple-500/10 text-purple-400 rounded-lg">🛡️</span>
                    </div>
                    <div class="text-4xl font-extrabold font-outfit text-white flex items-baseline gap-1.5">
                        {{ data.total_players_count }} <span class="text-xl font-semibold text-gray-400">Players</span>
                    </div>
                </div>
                <div class="text-xs text-transparent mt-2 pointer-events-none select-none">spacer</div>
            </div>

            <div class="bg-cardbg border border-rose-500/20 rounded-2xl p-6 shadow-xl backdrop-blur-xl hover:border-rose-500/40 transition-all group flex flex-col justify-between h-full">
                <div>
                    <div class="flex items-center justify-between mb-3">
                        <span class="text-rose-400 font-semibold text-sm">⚠️ 최다 첫 사망</span>
                        <span class="p-2 bg-rose-500/10 text-rose-400 rounded-lg group-hover:scale-110 transition-transform">❗</span>
                    </div>
                    <div class="text-4xl font-extrabold font-outfit {{ data.most_first_deaths.class_color_class }}">{{ data.most_first_deaths.name }}</div>
                </div>
                <div class="text-xs text-rose-300 mt-2">총 {{ data.most_first_deaths.count }}회 공대 최초 사망 기록</div>
            </div>

            <div class="bg-cardbg border border-amber-500/20 rounded-2xl p-6 shadow-xl backdrop-blur-xl hover:border-amber-500/40 transition-all group flex flex-col justify-between h-full">
                <div>
                    <div class="flex items-center justify-between mb-3">
                        <span class="text-amber-400 font-semibold text-sm">🛑 최다 단독 사망</span>
                        <span class="p-2 bg-amber-500/10 text-amber-400 rounded-lg group-hover:scale-110 transition-transform">💀</span>
                    </div>
                    <div class="text-4xl font-extrabold font-outfit {{ data.most_solo_blunders.class_color_class }}">{{ data.most_solo_blunders.name }}</div>
                </div>
                <div class="text-xs text-amber-300 mt-2">전후 5초간 동료 사망 없는 고립 데스 {{ data.most_solo_blunders.count }}회</div>
            </div>
        </div>

        <!-- Analytical Instructions / Legend & Collapsible Score Explanation -->
        <div class="bg-slate-900/60 border border-slate-800 rounded-xl p-6 mb-10 shadow-lg backdrop-blur-md space-y-5">
            <div class="flex flex-col md:flex-row gap-4 items-start md:items-center justify-between border-b border-slate-800/80 pb-5">
                <div class="space-y-2 text-sm text-gray-300">
                    <div class="font-bold text-indigo-400 flex items-center gap-2 text-base">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                        데이터 분석 기준 안내
                    </div>
                    <p>• <b>데이터 분석의 근거</b>: 3번째 사망자 발생 이후 시점은 무시되며, 10초 내로 현재 생존자의 50% 이상이 사망한다면 해당 이벤트 발생 시점의 첫 번째 사망자 이전의 데이터만 유효하게 간주합니다.</p>
                    <p>• <b>단독 사망</b>: 사망 전후 5초 이내에 다른 공대원의 사망이 없는 '순수 개인 실수' 지표입니다.</p>
                </div>
            </div>
            
            <div class="bg-gray-950/50 p-5 rounded-xl border border-gray-800/60 text-gray-300 space-y-3">
                <div class="font-bold text-amber-400 flex items-center gap-2 text-sm">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 7h6m0 10v-3m-3 3h.01M9 17h.01M9 14h.01M12 14h.01M15 11h.01M12 11h.01M9 11h.01M7 21h10a2 2 0 002-2V5a2 2 0 00-2-2H7a2 2 0 00-2 2v14a2 2 0 002 2z"></path></svg>
                    생존 점수 산정 방식
                </div>
                <p class="text-sm font-medium text-gray-200 leading-relaxed">
                    사망 시점과 생존률을 종합하여 생존 점수를 계산합니다
                </p>
                <details class="group border-t border-gray-800/60 pt-3 mt-2">
                    <summary class="flex items-center justify-between cursor-pointer list-none text-xs font-semibold text-indigo-400 hover:text-indigo-300 transition-colors py-1 pl-1">
                        <span>🔍 자세한 점수 및 컨디션 산정 방식</span>
                        <span class="transition-transform duration-200 group-open:rotate-180">▼</span>
                    </summary>
                    <div class="mt-3 bg-gray-900/80 p-4 rounded-lg border border-gray-800 text-xs leading-relaxed text-gray-300 space-y-4">
                        <div>
                            <div class="font-bold text-amber-300 mb-1.5 flex items-center gap-1">🛡️ 생존 점수 산정 방식 (기본 점수 100점 만점)</div>
                            <div class="space-y-1.5 pl-1">
                                • <span class="text-rose-300 font-semibold">첫 번째 사망</span>: 회당 -5점 직접 차감 + (개인 첫 사망 / 총 트라이) × 40점 차감<br>
                                • <span class="text-orange-300 font-semibold">두 번째 / 세 번째 사망</span>: 회당 -3점 / -1.5점 직접 차감 + 지분율에 따른 추가 차감<br>
                                • <span class="text-amber-300 font-semibold">단독 사망</span>: 회당 -4점 직접 차감 + (단독 사망 / 총 트라이) × 30점 차감<br>
                                • <span class="text-purple-300 font-semibold">Active.avg 손실률</span>: (1.0 - Active.avg) × 100점 차감<br>
                                • <span class="text-emerald-300 font-semibold">생존 가산점</span>: (생존 트라이 / 총 트라이) × 5점 가산점 부여
                            </div>
                        </div>
                        <div class="border-t border-gray-800/80 pt-3">
                            <div class="font-bold text-indigo-400 mb-1.5 flex items-center gap-1">📈 최근 컨디션 지표 산정 방식</div>
                            <div class="space-y-2.5 pl-1 text-gray-400">
                                <p class="text-[11px] leading-relaxed">
                                    최근 트라이 범위(3/5/7/10회) 내에서 발생한 사망 빈도와 시점을 종합 분석하여 컨디션을 평가합니다. 단순히 최근 흐름만 보는 통계 왜곡을 방지하기 위해 <b>사망 횟수가 많은 플레이어가 항상 더 높은 감점(낮은 등급)을 받도록 우선 정렬</b>한 후, <b>동일한 사망 횟수 내에서만 시간 가중치에 따라 점수를 미세 조정</b>합니다.
                                </p>
                                <ul class="space-y-1.5 pl-2 text-[11px] list-disc list-inside">
                                    <li><span class="text-gray-300 font-semibold">실책 빈도 비례 감점</span>: 선택한 최근 트라이 범위 내에서 사망 횟수가 많을수록 페널티가 누적되어 가중됩니다.</li>
                                    <li><span class="text-gray-300 font-semibold">시간 가중치 보정 (최대 40% 편차)</span>: 동일한 사망 횟수일 경우, 최근 트라이에 사망했을수록 집중력 저하 상태로 보아 감점이 강화되며, 과거 트라이에 사망하고 최근에 생존을 유지하고 있다면 감점이 완화됩니다.</li>
                                    <li><span class="text-emerald-400 font-semibold">🌟 최상 (Perfect)</span>: 선택 범위 내 사망이 0회이며, 전체 유효 사망률도 5% 미만인 에이스 상태.</li>
                                    <li><span class="text-sky-400 font-semibold">📈 상승 (+N%)</span>: 선택 범위 내 사망은 0회이나, 과거에 사망 이력이 있어 최근 생존력을 완전 회복한 상태 (과거 사망률 N% 표시).</li>
                                    <li><span class="text-amber-400 font-semibold">⚡ 주의</span>: 경미한 실책 경향성 보유 (최종 페널티 7점 미만).</li>
                                    <li><span class="text-orange-400 font-semibold">⚠️ 심각</span>: 잦은 실책 또는 최근 트라이 연속 사망 발생 (최종 페널티 7점 이상 ~ 14점 미만).</li>
                                    <li><span class="text-rose-400 font-semibold">💀 트롤</span>: 매우 높은 사망 빈도 및 지속적인 집중력 저하 상태 (최종 페널티 14점 이상).</li>
                                </ul>
                            </div>
                        </div>
                    </div>
                </details>
            </div>
        </div>

        <!-- Main Data Table Section -->
        <div class="bg-cardbg border border-gray-800 rounded-2xl p-6 shadow-2xl backdrop-blur-xl">
            <!-- 컨디션 분석 범위 조작 툴바 -->
            <div class="flex flex-col md:flex-row items-start md:items-center justify-between gap-4 mb-6 bg-gray-900/60 p-4 rounded-xl border border-gray-800">
                <div class="text-sm text-gray-300 font-semibold flex items-center gap-2">
                    <svg class="w-4 h-4 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"></path></svg>
                    <span>🎯 플레이어 컨디션 분석 범위 선택 (최근 트라이 사망 빈도 및 시점 반영):</span>
                </div>
                <div class="flex flex-wrap items-center gap-3 select-none">
                    <!-- AJAX 실시간 새로고침 버튼 -->
                    <button id="refreshDataBtn" onclick="refreshData()" class="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-200 hover:text-white font-semibold text-xs shadow transition-all active:scale-95">
                        <svg id="refreshIcon" class="w-3.5 h-3.5 text-indigo-400 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
                        <span>데이터 갱신</span>
                    </button>

                    <!-- ⭐ 10/7(기본)/5/3회 선택지 -->
                    <div class="inline-flex rounded-lg p-1 bg-gray-950 border border-gray-800 gap-1">
                        <button onclick="switchCondition('recent10', this)" class="condition-btn px-4 py-1.5 rounded-md bg-transparent text-gray-400 hover:text-white font-semibold text-xs transition-all">최근 10회</button>
                        <button onclick="switchCondition('recent7', this)" class="condition-btn px-4 py-1.5 rounded-md bg-indigo-600 text-white font-bold text-xs shadow transition-all">최근 7회 (기본)</button>
                        <button onclick="switchCondition('recent5', this)" class="condition-btn px-4 py-1.5 rounded-md bg-transparent text-gray-400 hover:text-white font-semibold text-xs transition-all">최근 5회</button>
                        <button onclick="switchCondition('recent3', this)" class="condition-btn px-4 py-1.5 rounded-md bg-transparent text-gray-400 hover:text-white font-semibold text-xs transition-all">최근 3회</button>
                    </div>
                </div>
            </div>

            <!-- 로그 원본 주소 이동 버튼 (테이블 상단 배치, 큰 폰트) -->
            <div class="mb-6 flex items-center justify-start border-l-4 border-rose-500 pl-4 py-2 bg-gray-900/40 rounded-r-xl shadow-inner">
                <a href="{{ data.raw_url }}" target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-2.5 text-base md:text-lg font-extrabold text-rose-400 hover:text-rose-300 hover:underline transition-all">
                    <svg class="w-5 h-5 text-rose-500 animate-pulse" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path></svg>
                    <span>로그 원본 주소로 이동 (새 창 열기)</span>
                </a>
            </div>

            <table id="survivalTable" class="display w-full text-left text-sm font-sans">
                <thead>
                    <tr class="bg-gray-800/80 text-indigo-300">
                        <th class="rounded-l-lg">플레이어</th>
                        <th>첫 번째 사망</th>
                        <th>두 번째 사망</th>
                        <th>세 번째 사망</th>
                        <th>단독 사망</th>
                        <th>초반 2인 이내 사망률</th>
                        <th>Active.avg</th>
                        <th>평균 생존 시간</th>
                        <th class="text-right">⭐ 생존 점수</th>
                        <th class="rounded-r-lg text-center">최근 컨디션</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-gray-800">
                    {% for p in data.players %}
                    <tr>
                        <td class="font-bold text-base {{ p.class_color_class }}" data-order="{{ p.name }}">
                            {{ p.name }}
                        </td>
                        <td class="font-semibold {% if p.first_deaths > 0 %}text-rose-400{% else %}text-gray-400{% endif %}" data-order="{{ p.first_deaths }}">{{ p.first_deaths }}회</td>
                        <td class="text-gray-300" data-order="{{ p.second_deaths }}">{{ p.second_deaths }}회</td>
                        <td class="text-gray-400" data-order="{{ p.third_deaths }}">{{ p.third_deaths }}회</td>
                        <td class="font-semibold {% if p.solo_blunders > 0 %}text-amber-400{% else %}text-gray-400{% endif %}" data-order="{{ p.solo_blunders }}">{{ p.solo_blunders }}회</td>
                        <td class="font-bold text-indigo-400" data-order="{{ p.top2_ratio_num }}">{{ p.top2_ratio }}</td>
                        <td class="font-semibold text-gray-200" data-order="{{ p.survival_rate_num }}">{{ p.survival_rate }}</td>
                        <td class="text-gray-400" data-order="{{ p.avg_time_num }}">{{ p.avg_time }}</td>
                        <td class="text-right font-black text-lg font-outfit {% if p.score >= 90 %}text-emerald-400{% elif p.score >= 80 %}text-sky-400{% elif p.score >= 65 %}text-amber-400{% elif p.score >= 50 %}text-orange-400{% else %}text-rose-500{% endif %}" data-order="{{ p.score }}">
                            {{ p.score }}점
                        </td>
                        <td class="condition-col text-center" data-order="{{ p.condition_recent7.order }}">
                            <!-- ⭐ 툴팁 깜빡임 상속 방지를 위해 정적 부모 컨테이너(condition-wrapper) 분리 -->
                            <div class="condition-wrapper relative inline-block group cursor-pointer"
                                  data-recent10-badge="{{ p.condition_recent10.badge }}" data-recent10-text="{{ p.condition_recent10.text }}" data-recent10-class="{{ p.condition_recent10.class }}" data-recent10-order="{{ p.condition_recent10.order }}" data-recent10-tooltip="{{ p.tooltip_recent10 | escape }}"
                                  data-recent7-badge="{{ p.condition_recent7.badge }}" data-recent7-text="{{ p.condition_recent7.text }}" data-recent7-class="{{ p.condition_recent7.class }}" data-recent7-order="{{ p.condition_recent7.order }}" data-recent7-tooltip="{{ p.tooltip_recent7 | escape }}"
                                  data-recent5-badge="{{ p.condition_recent5.badge }}" data-recent5-text="{{ p.condition_recent5.text }}" data-recent5-class="{{ p.condition_recent5.class }}" data-recent5-order="{{ p.condition_recent5.order }}" data-recent5-tooltip="{{ p.tooltip_recent5 | escape }}"
                                  data-recent3-badge="{{ p.condition_recent3.badge }}" data-recent3-text="{{ p.condition_recent3.text }}" data-recent3-class="{{ p.condition_recent3.class }}" data-recent3-order="{{ p.condition_recent3.order }}" data-recent3-tooltip="{{ p.tooltip_recent3 | escape }}">
                                <span class="condition-badge inline-flex items-center gap-2 px-3.5 py-1.5 rounded-2xl text-xs font-semibold border {{ p.condition_recent7.class }}">
                                    <span class="text-base">{{ p.condition_recent7.badge }}</span> <span class="text-center leading-tight">{{ p.condition_recent7.text | safe }}</span>
                                </span>
                                {{ p.tooltip_recent7 | safe }}
                            </div>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <footer class="mt-16 text-center text-xs text-gray-600 border-t border-gray-900 pt-6">
            <p>Warcraft Logs Web API v2 Integration • Powered by Advanced AI Wipe Detection Algorithm</p>
        </footer>
    </div>
    <script>
        $(document).ready( function () {
            $('#survivalTable').DataTable({ 
                paging: false, 
                order: [[8, 'asc']], // ⭐ 생존 점수가 8번 인덱스 유지
                language: {
                    search: "공대원 검색:",
                    info: "총 _TOTAL_명의 공대원 분석 데이터",
                    infoEmpty: "검색 결과가 없습니다.",
                    zeroRecords: "일치하는 공대원이 없습니다."
                }
            });

            // ⭐ 데이터 갱신 후 이전 스크롤 위치 완벽 복구
            var savedScroll = sessionStorage.getItem('savedScrollPosition');
            if (savedScroll !== null) {
                $(window).scrollTop(parseFloat(savedScroll));
                sessionStorage.removeItem('savedScrollPosition');
            }

            // 툴팁 고정(Pin) 토글 및 외부 클릭 시 닫기 기능
            $(document).on('click', function(e) {
                var wrapper = $(e.target).closest('.condition-wrapper');
                if (wrapper.length > 0) {
                    if ($(e.target).closest('.condition-tooltip').length > 0) {
                        return; // 툴팁 내부 클릭 시 닫히지 않도록 보호
                    }
                    // 다른 열린 툴팁은 닫고 현재 클릭한 뱃지만 토글
                    $('.condition-wrapper').not(wrapper).removeClass('pinned');
                    wrapper.toggleClass('pinned');
                } else {
                    // 빈 공간(외부) 클릭 시 모든 툴팁 즉시 닫기
                    $('.condition-wrapper').removeClass('pinned');
                }
            });
        });

        function switchCondition(mode, btn) {
            $('.condition-btn').removeClass('bg-indigo-600 text-white font-bold shadow').addClass('bg-transparent text-gray-400 font-semibold');
            $(btn).removeClass('bg-transparent text-gray-400 font-semibold').addClass('bg-indigo-600 text-white font-bold shadow');

            var table = $('#survivalTable').DataTable();
            
            $('.condition-wrapper').each(function() {
                var badgeText = $(this).attr('data-' + mode + '-badge');
                var descText = $(this).attr('data-' + mode + '-text');
                var className = $(this).attr('data-' + mode + '-class');
                var orderVal = $(this).attr('data-' + mode + '-order');
                var tooltipHtml = $(this).attr('data-' + mode + '-tooltip');

                // 기존 고정(pinned) 상태 유지
                var isPinned = $(this).hasClass('pinned') ? ' pinned' : '';

                var badgeHtml = '<span class="condition-badge inline-flex items-center gap-2 px-3.5 py-1.5 rounded-2xl text-xs font-semibold border ' + className + '"><span class="text-base">' + badgeText + '</span> <span class="text-center leading-tight">' + descText + '</span></span>';

                $(this).attr('class', 'condition-wrapper relative inline-block group cursor-pointer' + isPinned);
                $(this).html(badgeHtml + tooltipHtml);
                
                $(this).closest('td').attr('data-order', orderVal);
            });

            table.rows().invalidate().draw(false);
        }

        function refreshData() {
            var btn = $('#refreshDataBtn');
            var icon = $('#refreshIcon');
            btn.prop('disabled', true).addClass('opacity-70');
            icon.addClass('animate-spin');
            
            // ⭐ 갱신 전 현재 스크롤 위치를 sessionStorage에 안전하게 저장
            sessionStorage.setItem('savedScrollPosition', $(window).scrollTop());
            
            fetch('/api/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: "{{ data.raw_url }}" })
            })
            .then(response => {
                if (!response.ok) {
                    return response.text().then(errText => { throw new Error(errText); });
                }
                return response.text();
            })
            .then(html => {
                document.open();
                document.write(html);
                document.close();
            })
            .catch(error => {
                alert('⚠️ 데이터 갱신 중 오류가 발생했습니다: ' + error.message);
                btn.prop('disabled', false).removeClass('opacity-70');
                icon.removeClass('animate-spin');
            });
        }
    </script>
</body>
</html>
"""

@app.route('/')
def home():
    url_param = request.args.get('url')
    if url_param:
        print(f"\n[알림] ▶ 웹 브라우저 새로고침(GET ?url=...) 감지: {url_param}")
        parsed = parse_wcl_url(url_param)
        if not parsed:
            return render_template_string(LANDING_HTML_TEMPLATE, error="URL에서 리포트 코드를 찾을 수 없습니다.")
        report_code = parsed['report_code']
        boss = parsed['boss']
        data = get_parsed_data(report_code, boss)
        if "error" in data:
            return render_template_string(LANDING_HTML_TEMPLATE, error=data['error'])
        data['raw_url'] = url_param
        return render_template_string(REPORT_HTML_TEMPLATE, data=data)

    print("\n[알림] ▶ 웹 브라우저에서 메인 랜딩 페이지 접속 요청을 감지했습니다!")
    return render_template_string(LANDING_HTML_TEMPLATE, error=None)

@app.route('/api/analyze', methods=['POST'])
def analyze():
    req_data = request.get_json()
    if not req_data or 'url' not in req_data:
        return "잘못된 요청입니다. URL을 입력해 주세요.", 400
    
    raw_url = req_data['url']
    print(f"\n[알림] ▶ 분석 요청 수신: {raw_url}")
    parsed = parse_wcl_url(raw_url)
    
    if not parsed:
        print("[오류] 리포트 코드를 추출할 수 없습니다.")
        return "URL에서 리포트 코드를 찾을 수 없습니다. 주소를 확인해 주세요.", 400
    
    report_code = parsed['report_code']
    boss = parsed['boss']
    
    print(f"[알림] ▶ 파싱 성공: 코드={report_code}, boss={boss}. API 조회 시작...")
    data = get_parsed_data(report_code, boss)
    
    if "error" in data:
        print(f"[오류] {data['error']}")
        return data['error'], 404
    
    data['raw_url'] = raw_url
    print("[알림] ▶ 분석 완료! 대시보드 HTML 렌더링 중...")
    return render_template_string(REPORT_HTML_TEMPLATE, data=data)

if __name__ == '__main__':
    app.run(debug=True, port=5001)