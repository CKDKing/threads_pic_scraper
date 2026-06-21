# -*- coding: utf-8 -*-
"""
Threads Pokemon Infographic Image Scraper
爬取 threads.net/@jchannelzz 帳號最近一個月內的寶可夢資訊圖片，並保存至 POKEINFO 資料夾。
支援增量爬取（透過 crawl_log.json 紀錄）。
"""

import os
import re
import sys
import json
import urllib.parse
import warnings
from datetime import datetime, timedelta
import requests
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# 忽略外部警告，保持 Console 乾淨
warnings.filterwarnings("ignore")

# 確保輸出支援 UTF-8 (特別是在 Windows 中文環境下)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

# --- 全局常數設定 ---
TARGET_URL = "https://www.threads.net/@jchannelzz?hl=zh-tw"
OUTPUT_DIR = r"D:\Program Files\Google Drive\POKEINFO"
LOG_FILE = "crawl_log.json"
HISTORY_FILE = "crawl_history.txt"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def setup_environment() -> None:
    """初始化輸出目錄與日誌相關設定"""
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"已建立圖片輸出目錄: {OUTPUT_DIR}")

def load_crawl_log() -> dict:
    """讀取爬蟲紀錄日誌"""
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"讀取日誌失敗，將重新建立日誌。錯誤: {e}")
    
    return {"last_crawled_time": None, "crawled_post_ids": []}

def save_crawl_log(log_data: dict) -> None:
    """保存爬蟲紀錄日誌"""
    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(log_data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"保存日誌失敗: {e}")

def write_history_log(date_str: str, post_url: str, images_saved: list) -> None:
    """記錄人類易讀的歷史紀錄檔"""
    try:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            saved_names = ", ".join(images_saved)
            f.write(f"[{timestamp}] 日期: {date_str} | 貼文: {post_url} | 下載圖片: {saved_names}\n")
    except Exception as e:
        print(f"寫入歷史紀錄失敗: {e}")

def download_image(url: str, filepath: str) -> bool:
    """下載圖片並保存至本地，並檢查解析度是否符合規格"""
    headers = {"User-Agent": USER_AGENT}
    try:
        response = requests.get(url, headers=headers, timeout=20)
        if response.status_code == 200:
            with open(filepath, "wb") as f:
                f.write(response.content)
            
            # 使用 Pillow 檢查解析度是否符合 1920x1080 或 2160x1234
            try:
                from PIL import Image
                with Image.open(filepath) as img:
                    w, h = img.size
                    if (w == 1920 and h == 1080) or (w == 2160 and h == 1234):
                        return True
                    else:
                        print(f"  圖片解析度為 {w}x{h}，不符合規格 (1920x1080 或 2160x1234)，將刪除此圖片。")
                        img.close()
                        if os.path.exists(filepath):
                            os.remove(filepath)
                        return False
            except Exception as img_err:
                print(f"  檢查圖片解析度時發生錯誤: {img_err}")
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except:
                        pass
                return False
        else:
            print(f"  圖片下載失敗，HTTP 狀態碼: {response.status_code}")
    except Exception as e:
        print(f"  圖片下載發生異常: {e}")
    return False

def parse_utc_time(dt_str: str) -> datetime:
    """將 ISO UTC 時間字串轉換為 Python datetime (含時區處理)"""
    return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))

def get_taiwan_time(utc_dt: datetime) -> datetime:
    """將 UTC 時間轉換為台灣時間 (UTC+8)"""
    return utc_dt + timedelta(hours=8)

def extract_json_block(text: str, start_pattern: str) -> str:
    """從文本中提取首個平衡大括號的 JSON 區塊"""
    match = re.search(start_pattern, text)
    if not match:
        return None
        
    start_idx = match.start()
    brace_count = 0
    end_idx = -1
    for i in range(start_idx, len(text)):
        char = text[i]
        if char == '{':
            brace_count += 1
        elif char == '}':
            brace_count -= 1
            if brace_count == 0:
                end_idx = i + 1
                break
                
    if end_idx != -1:
        return text[start_idx:end_idx]
    return None

def find_key_recursive(data, target_key):
    """遞迴搜尋巢狀資料結構中的特定鍵"""
    if isinstance(data, dict):
        if target_key in data:
            return data[target_key]
        for key, value in data.items():
            res = find_key_recursive(value, target_key)
            if res:
                return res
    elif isinstance(data, list):
        for item in data:
            res = find_key_recursive(item, target_key)
            if res:
                return res
    return None

def extract_main_post_images(soup: BeautifulSoup) -> tuple:
    """從頁面的 Relay JSON 或 DOM 中解析主貼文圖片與內文"""
    # 優先從 Relay JSON 提取，這能百分之百精準篩選主貼文內容與其圖片
    for script in soup.find_all("script"):
        text = script.get_text()
        if not text:
            continue
            
        if "adp_BarcelonaPermalinkMobilePostColumnPageQueryRelayPreloader" in text:
            json_str = extract_json_block(text, r'\{"__bbox"')
            if json_str:
                try:
                    data = json.loads(json_str)
                    media = find_key_recursive(data, "media")
                    if media:
                        caption = media.get("caption", {}).get("text", "")
                        
                        image_urls = []
                        carousel = media.get("carousel_media")
                        if carousel:
                            for item in carousel:
                                candidates = item.get("image_versions2", {}).get("candidates", [])
                                matched_url = None
                                for cand in candidates:
                                    w = cand.get("width")
                                    h = cand.get("height")
                                    if (w == 1920 and h == 1080) or (w == 2160 and h == 1234):
                                        matched_url = cand.get("url")
                                        break
                                image_urls.append(matched_url)
                        else:
                            candidates = media.get("image_versions2", {}).get("candidates", [])
                            matched_url = None
                            for cand in candidates:
                                w = cand.get("width")
                                h = cand.get("height")
                                if (w == 1920 and h == 1080) or (w == 2160 and h == 1234):
                                    matched_url = cand.get("url")
                                    break
                            image_urls.append(matched_url)
                                
                        return caption, image_urls
                except Exception:
                    pass

    # 備用方案: 從 DOM 直接篩選前幾個非頭像圖片
    print("  無法由 JSON 提取，改用備用 DOM 提取方案...")
    post_images = []
    # 提取所有 instagram 圖片網址，並排除常見的 avatar 尺寸（2885-19、82787-19）
    for img in soup.find_all("img"):
        src = img.get("src")
        alt = img.get("alt", "")
        if not src:
            continue
        is_avatar = "2885-19" in src or "82787-19" in src or "的大頭貼照" in alt or "大頭貼照" in alt
        is_external = "external" in src
        if "fbcdn.net" in src and not is_avatar and not is_external:
            if src not in post_images:
                post_images.append(src)
                
    meta_desc = soup.find("meta", attrs={"name": "description"})
    caption = meta_desc.get("content") if meta_desc else ""
    
    return caption, post_images

def scrape_threads() -> None:
    """主爬蟲程序"""
    setup_environment()
    log_data = load_crawl_log()
    
    now = datetime.now()
    if log_data["last_crawled_time"]:
        cutoff_dt = parse_utc_time(log_data["last_crawled_time"])
        print(f"開始增量爬取，起始時間點為上次紀錄: {get_taiwan_time(cutoff_dt).strftime('%Y-%m-%d %H:%M:%S')} (台灣時間)")
    else:
        cutoff_dt = parse_utc_time((now - timedelta(days=30)).isoformat() + "Z")
        print(f"未偵測到過往爬取日誌，將爬取最近一個月內的貼文。起始時間: {get_taiwan_time(cutoff_dt).strftime('%Y-%m-%d %H:%M:%S')}")

    newest_post_time = None
    crawled_ids = set(log_data.get("crawled_post_ids", []))
    
    with sync_playwright() as p:
        print("啟動無頭瀏覽器...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT,
            locale="zh-TW"
        )
        page = context.new_page()
        
        print(f"正在導航至主頁: {TARGET_URL}")
        page.goto(TARGET_URL)
        page.wait_for_timeout(5000)
        
        print("滾動頁面加載歷史貼文...")
        last_height = page.evaluate("document.body.scrollHeight")
        for scroll_idx in range(5):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
            
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        post_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            match = re.search(r"/@jchannelzz/post/([^/]+)", href)
            if match:
                post_id = match.group(1)
                post_url = f"https://www.threads.net/@jchannelzz/post/{post_id}"
                if post_url not in post_links:
                    post_links.append(post_url)
                    
        print(f"主頁解析完成，共發現 {len(post_links)} 篇可能貼文。開始逐篇篩選與下載...")
        
        downloaded_count = 0
        new_crawled_ids = []
        
        for idx, post_url in enumerate(post_links):
            post_id = post_url.split("/")[-1]
            if post_id in crawled_ids:
                continue
                
            print(f"\n[{idx+1}/{len(post_links)}] 正在解析貼文: {post_url}")
            try:
                page.goto(post_url)
                page.wait_for_timeout(4000) # 確保動態圖片與 Relay JSON 加載完畢
                
                post_html = page.content()
                post_soup = BeautifulSoup(post_html, "html.parser")
                
                # 尋找發布時間：第一個 time 元素
                time_el = post_soup.find("time")
                if not time_el or not time_el.get("datetime"):
                    print("  無法取得發布時間，跳過此貼文")
                    continue
                    
                pub_time_str = time_el["datetime"]
                pub_dt = parse_utc_time(pub_time_str)
                local_pub_dt = get_taiwan_time(pub_dt)
                
                # 檢查是否超出時間範圍
                if pub_dt <= cutoff_dt:
                    print(f"  貼文時間 {local_pub_dt.strftime('%Y-%m-%d %H:%M:%S')} 已超出爬取範圍，跳過")
                    continue
                
                # 紀錄本次運行的最新發布時間
                if newest_post_time is None or pub_dt > newest_post_time:
                    newest_post_time = pub_dt
                    
                # 提取貼文內容與主貼文上傳圖片
                post_text, post_images = extract_main_post_images(post_soup)
                img_count = len(post_images)
                valid_img_count = sum(1 for img in post_images if img is not None)
                
                print(f"  貼文時間: {local_pub_dt.strftime('%Y-%m-%d %H:%M:%S')} | 上傳圖片數: {img_count} (符合規格數: {valid_img_count})")
                
                if valid_img_count == 0:
                    print("  此貼文無符合 1920x1080 或 2160x1234 規格的圖片，跳過")
                    new_crawled_ids.append(post_id)
                    continue
                    
                final_images = post_images
                
                # 開始下載圖片
                date_str = local_pub_dt.strftime("%Y%m%d")
                time_str = local_pub_dt.strftime("%H%M%S")
                images_saved_names = []
                
                for image_idx, img_url in enumerate(final_images):
                    if img_url is None:
                        continue
                        
                    num_suffix = image_idx + 1
                    filename = f"Pokeinfo_{date_str}_{time_str}_{num_suffix}.png"
                    filepath = os.path.join(OUTPUT_DIR, filename)
                    
                    # 衝突防護：極端情況下若檔名仍存在，則補上 dup 標記
                    if os.path.exists(filepath):
                        filename = f"Pokeinfo_{date_str}_{time_str}_{num_suffix}_dup.png"
                        filepath = os.path.join(OUTPUT_DIR, filename)
                        
                    print(f"  下載圖片中 -> {filename}")
                    success = download_image(img_url, filepath)
                    if success:
                        images_saved_names.append(filename)
                        downloaded_count += 1
                        
                if images_saved_names:
                    write_history_log(date_str, post_url, images_saved_names)
                    
                new_crawled_ids.append(post_id)
                
            except Exception as post_err:
                print(f"  解析此貼文時發生異常: {post_err}")
                
        # 更新爬蟲日誌
        if newest_post_time:
            log_data["last_crawled_time"] = newest_post_time.isoformat().replace("+00:00", "Z")
        log_data["crawled_post_ids"] = list(crawled_ids.union(new_crawled_ids))
        save_crawl_log(log_data)
        
        browser.close()
        
    print(f"\n爬蟲運行結束。本次共成功下載了 {downloaded_count} 張圖片！")

if __name__ == "__main__":
    scrape_threads()
