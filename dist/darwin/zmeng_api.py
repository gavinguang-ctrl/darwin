import re
import os
import requests
import pandas as pd


def _get_token() -> str:
    return os.environ.get("ZMENG_AUTH_TOKEN", "")


def _get_cookie() -> str:
    return os.environ.get("ZMENG_COOKIE", "")

API_URL = "https://tt.zmeng123.com/alived/live/list"


def parse_metric_value(val, is_duration: bool = False) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    s = s.replace(",", "")
    # 时长格式: "1m30s", "2m", "45s", "1h2m30s"
    if is_duration:
        total = 0.0
        h_match = re.search(r'(\d+)\s*h', s, re.IGNORECASE)
        m_match = re.search(r'(\d+)\s*m', s, re.IGNORECASE)
        s_match = re.search(r'(\d+)\s*s', s, re.IGNORECASE)
        if h_match or m_match or s_match:
            if h_match:
                total += int(h_match.group(1)) * 3600
            if m_match:
                total += int(m_match.group(1)) * 60
            if s_match:
                total += int(s_match.group(1))
            return total
        # 纯数字，原样返回
        s = re.sub(r'[^\d.]', '', s)
        try:
            return float(s) if s else 0.0
        except ValueError:
            return 0.0
    s = re.sub(r'^[^\d.%-]*', '', s)
    if not s:
        return 0.0
    s = s.rstrip('%')
    multiplier = 1
    if s.upper().endswith('K'):
        s = s[:-1]
        multiplier = 1000
    elif s.upper().endswith('M'):
        s = s[:-1]
        multiplier = 1000000
    if s.endswith('s'):
        s = s[:-1]
    try:
        return float(s) * multiplier
    except ValueError:
        return 0.0


def fetch_live_data(room_id: str) -> dict | None:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Authorization": _get_token(),
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://tt.zmeng123.com",
        "Referer": "https://tt.zmeng123.com/",
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X)",
    }
    cookies = {}
    if _get_cookie():
        for pair in _get_cookie().split("; "):
            if "=" in pair:
                k, v = pair.split("=", 1)
                cookies[k.strip()] = v.strip()

    payload = {"pageNum": 1, "pageSize": 1, "roomId": room_id}
    try:
        resp = requests.post(API_URL, json=payload, headers=headers, cookies=cookies, timeout=15)
        data = resp.json()
    except Exception:
        return None

    if data.get("errorCode") != 0 or not data.get("data", {}).get("list"):
        return None

    item = data["data"]["list"][0]
    return {
        "ctr": parse_metric_value(item.get("ctr")),
        "dwell_time": parse_metric_value(item.get("avgViewDuration"), is_duration=True),
        "gpm": parse_metric_value(item.get("showGPM")),
        "gmv": parse_metric_value(item.get("gmv")),
        "order_volume": parse_metric_value(item.get("itemsSold")),
        "follow_rate": parse_metric_value(item.get("followRate")),
        "views": parse_metric_value(item.get("views")),
        "impressions": parse_metric_value(item.get("impressions")),
        "roi": parse_metric_value(item.get("gmvMaxROI")),
        "_host": item.get("hostName", ""),
        "_duration": item.get("duration", ""),
        "_open_time": item.get("openTime", ""),
        "_room_url": item.get("roomUrl", ""),
    }


def extract_script_from_excel(file) -> str:
    df = pd.read_excel(file, header=None)
    parts = []
    for _, row in df.iterrows():
        line = " ".join(str(c) for c in row if pd.notna(c) and str(c).strip())
        if line:
            parts.append(line)
    return "\n".join(parts)


def script_to_excel_bytes(script: str) -> bytes:
    """将脚本文本按行写入 Excel，与上传格式一致"""
    from io import BytesIO
    lines = [line for line in script.split("\n") if line.strip()]
    df = pd.DataFrame(lines, columns=None)
    buf = BytesIO()
    df.to_excel(buf, index=False, header=False)
    return buf.getvalue()


TASK_LIST_URL = "https://tt.zmeng123.com/alived/live/gemini/task/list"
TASK_CONTENT_URL = "https://tt.zmeng123.com/alived/live/gemini/task/content"


def _get_headers_cookies() -> tuple[dict, dict]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Authorization": _get_token(),
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://tt.zmeng123.com",
        "Referer": "https://tt.zmeng123.com/",
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X)",
    }
    cookies = {}
    if _get_cookie():
        for pair in _get_cookie().split("; "):
            if "=" in pair:
                k, v = pair.split("=", 1)
                cookies[k.strip()] = v.strip()
    return headers, cookies


def fetch_host_rooms(host_name: str, start_date: str = "", end_date: str = "", page_size: int = 50) -> list[dict]:
    """获取指定主播的所有直播间列表（含数据和geminiTaskId）"""
    headers, cookies = _get_headers_cookies()
    all_rooms = []
    page = 1
    if not end_date:
        from datetime import datetime as _dt
        end_date = _dt.now().strftime("%Y-%m-%d")
    if not start_date:
        start_date = "2025-01-01"
    while True:
        payload = {"pageNum": page, "pageSize": page_size, "liveStatus": 0,
                   "hostName": host_name, "startDate": start_date, "endDate": end_date}
        try:
            resp = requests.post(API_URL, json=payload, headers=headers, cookies=cookies, timeout=15)
            data = resp.json()
        except Exception:
            break
        if data.get("errorCode") != 0 or not data.get("data", {}).get("list"):
            break
        items = data["data"]["list"]
        for item in items:
            room_data = {
                "roomId": item.get("roomId", ""),
                "hostName": item.get("hostName", ""),
                "openTime": item.get("openTime", ""),
                "geminiTaskId": item.get("geminiTaskId", ""),
                "ctr": parse_metric_value(item.get("ctr")),
                "dwell_time": parse_metric_value(item.get("avgViewDuration"), is_duration=True),
                "gmv": parse_metric_value(item.get("gmv")),
                "order_volume": parse_metric_value(item.get("itemsSold")),
                "follow_rate": parse_metric_value(item.get("followRate")),
                "views": parse_metric_value(item.get("views")),
                "impressions": parse_metric_value(item.get("impressions")),
                "roi": parse_metric_value(item.get("gmvMaxROI")),
                "duration": item.get("duration", ""),
            }
            all_rooms.append(room_data)
        total = data["data"].get("total", 0)
        if page * page_size >= total:
            break
        page += 1
    return all_rooms


def fetch_rooms_by_ids(room_ids: list[str]) -> list[dict]:
    """通过直播间ID列表获取直播数据（含geminiTaskId）"""
    headers, cookies = _get_headers_cookies()
    all_rooms = []
    for rid in room_ids:
        rid = rid.strip()
        if not rid:
            continue
        payload = {"pageNum": 1, "pageSize": 1, "roomId": rid}
        try:
            resp = requests.post(API_URL, json=payload, headers=headers, cookies=cookies, timeout=15)
            data = resp.json()
        except Exception:
            continue
        if data.get("errorCode") != 0 or not data.get("data", {}).get("list"):
            continue
        item = data["data"]["list"][0]
        all_rooms.append({
            "roomId": item.get("roomId", ""),
            "hostName": item.get("hostName", ""),
            "openTime": item.get("openTime", ""),
            "geminiTaskId": item.get("geminiTaskId", ""),
            "ctr": parse_metric_value(item.get("ctr")),
            "dwell_time": parse_metric_value(item.get("avgViewDuration"), is_duration=True),
            "gmv": parse_metric_value(item.get("gmv")),
            "order_volume": parse_metric_value(item.get("itemsSold")),
            "follow_rate": parse_metric_value(item.get("followRate")),
            "views": parse_metric_value(item.get("views")),
            "impressions": parse_metric_value(item.get("impressions")),
            "roi": parse_metric_value(item.get("gmvMaxROI")),
            "duration": item.get("duration", ""),
        })
    return all_rooms


def fetch_task_content(gemini_task_id: str) -> dict | None:
    headers, cookies = _get_headers_cookies()
    try:
        resp = requests.post(TASK_CONTENT_URL, json={"geminiTaskId": gemini_task_id},
                             headers=headers, cookies=cookies, timeout=30)
        data = resp.json()
    except Exception:
        return None
    if data.get("errorCode") != 0 or not data.get("data"):
        return None
    d = data["data"]
    scripts = sorted(d.get("scripts", []), key=lambda s: s.get("sequenceNo", 0))
    return {
        "id": d.get("id"),
        "taskName": d.get("taskName", ""),
        "prompt": d.get("prompt", ""),
        "scripts": [{"seq": s.get("sequenceNo", 0), "content": s.get("content", "")}
                     for s in scripts if s.get("content")],
        "script_count": len(scripts),
    }
