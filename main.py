# ==============================================================================
# 區塊 1: 匯入所有必要的函式庫
# ==============================================================================
import json
import os
import requests
import feedparser
import time
import argparse # 新增：用於處理指令列參數
from datetime import datetime, timezone # 新增：用於處理時間

from googleapiclient.discovery import build
# 修正：確保從函式庫中正確匯入 YouTubeTranscriptApi 這個類別
from youtube_transcript_api import YouTubeTranscriptApi
from pytube import YouTube
from bs4 import BeautifulSoup

# 語音轉文字的 Whisper 函式庫
try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    print("警告：Whisper 函式庫未安裝，語音轉文字功能將無法使用。")
    WHISPER_AVAILABLE = False


# ==============================================================================
# 區塊 2: 設定與輔助函式
# ==============================================================================

# 讀取設定檔
def load_config():
    """從 config.json 讀取設定"""
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("錯誤：找不到 config.json 檔案。")
        return None
    except json.JSONDecodeError:
        print("錯誤：config.json 格式不正確。")
        return None

# 讀寫已處理過的 ID
PROCESSED_IDS_FILE = 'processed_ids.txt'

def load_processed_ids():
    """從 processed_ids.txt 載入已處理的 ID，避免重複處理"""
    if not os.path.exists(PROCESSED_IDS_FILE):
        return set()
    with open(PROCESSED_IDS_FILE, 'r', encoding='utf-8') as f:
        return set(line.strip() for line in f)

def save_processed_id(item_id):
    """將新的已處理 ID 寫入檔案"""
    with open(PROCESSED_IDS_FILE, 'a', encoding='utf-8') as f:
        f.write(f"{item_id}\n")

# ==============================================================================
# 區塊 3: 內容獲取與處理函式
# ==============================================================================

def get_youtube_transcript(video_id):
    """獲取 YouTube 影片逐字稿，若無字幕則嘗試語音轉文字"""
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['zh-TW', 'zh-Hant', 'en', 'zh-Hans'])
        return " ".join([item['text'] for item in transcript_list])
    except Exception as e:
        print(f"影片 {video_id} 找不到現有字幕: {e}。嘗試進行語音轉文字...")
        if not WHISPER_AVAILABLE:
            print("Whisper 未安裝，跳過語音轉文字。")
            return None
        
        try:
            yt = YouTube(f"https://www.youtube.com/watch?v={video_id}")
            audio_stream = yt.streams.filter(only_audio=True).first()
            
            temp_dir = "temp_audio"
            if not os.path.exists(temp_dir):
                os.makedirs(temp_dir)
                
            audio_file = audio_stream.download(output_path=temp_dir)
            
            print("正在使用 Whisper 進行語音轉文字，這可能需要一些時間...")
            model = whisper.load_model("base")
            result = model.transcribe(audio_file)
            
            os.remove(audio_file) # 刪除暫存音檔
            return result['text']
            
        except Exception as stt_error:
            print(f"影片 {video_id} 語音轉文字失敗: {stt_error}")
            return None

def get_article_text(url):
    """從網頁 URL 獲取主要文章內容"""
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        soup = BeautifulSoup(response.text, 'html.parser')
        article_body = soup.find('article') or soup.find('main')
        if article_body:
            paragraphs = article_body.find_all('p')
            return "\n".join([p.get_text() for p in paragraphs])
        else:
            return "無法自動提取文章主體，請查看原始網頁。"
    except Exception as e:
        print(f"讀取文章 {url} 失敗: {e}")
        return None

def get_summary_from_llm(content, api_key):
    """(示意函式) 將內容傳送給語言模型以獲取摘要"""
    print("正在產生摘要...")
    if not api_key or "請在這裡" in api_key:
         return "摘要功能未設定：請在 config.json 中提供有效的 LLM_API_KEY。"
    return f"這是一個範例摘要。\n1. 這是第一點。\n2. 這是第二點。\n3. 原文的前100個字為：{content[:100]}..."

# ==============================================================================
# 區塊 4: 輸出與通知函式
# ==============================================================================

def broadcast_line_message(access_token, message):
    """(廣播版) 使用 Messaging API 發送廣播訊息給所有好友"""
    if not access_token or "請在這裡" in access_token:
        print("未設定 LINE Channel Access Token，略過發送。")
        return

    url = "https://api.line.me/v2/bot/message/broadcast"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"}
    data = {"messages": [{"type": "text", "text": message}]}

    try:
        response = requests.post(url, headers=headers, data=json.dumps(data))
        if response.status_code == 200:
             print("廣播訊息已成功發送。")
        else:
            print(f"LINE 廣播訊息發送失敗: {response.status_code} {response.text}")
    except Exception as e:
        print(f"LINE 廣播訊息發送時發生錯誤: {e}")

def save_to_markdown(title, url, summary, content):
    """將結果儲存為 Markdown 檔案"""
    if not os.path.exists('output'):
        os.makedirs('output')
    safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
    filename = f"output/{datetime.now().strftime('%Y%m%d')}_{safe_title}.md"
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(f"# {title}\n\n**來源網址:** [{url}]({url})\n\n---\n\n")
        f.write(f"## 重點摘要\n\n{summary.replace('n', 'nn')}\n\n---\n\n")
        f.write(f"## 全文/逐字稿\n\n{content.replace('n', 'nn')}")
    print(f"內容已儲存至: {filename}")

# ==============================================================================
# 區塊 5: 主流程與檢查器 (已整合年月搜尋功能)
# ==============================================================================

def process_item(item_id, title, url, content, config):
    """統一處理單個項目：摘要、通知、儲存"""
    summary = get_summary_from_llm(content, config.get("LLM_API_KEY"))
    line_message = f"【新內容廣播】\n\n標題：{title}\n網址：{url}\n\n摘要：\n{summary}"
    broadcast_line_message(config.get("LINE_CHANNEL_ACCESS_TOKEN"), line_message)
    save_to_markdown(title, url, summary, content)
    save_processed_id(item_id)
    print(f"已成功處理並廣播項目: {title}\n")

def check_youtube_channel(source, api_key, processed_ids, year=None, month=None):
    """檢查單個 YouTube 頻道，支援時間過濾"""
    print(f"--- 正在檢查 YouTube 頻道: {source['name']} ---")
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        
        # 新增：處理時間過濾參數
        published_after = None
        published_before = None
        if year and month:
            start_time = datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)
            # 計算下個月的第一天
            if month == 12:
                end_time = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
            else:
                end_time = datetime(year, month + 1, 1, 0, 0, 0, tzinfo=timezone.utc)
            published_after = start_time.isoformat()
            published_before = end_time.isoformat()
            print(f"時間範圍過濾已啟用: 從 {published_after} 到 {published_before}")

        request = youtube.search().list(
            part="snippet",
            channelId=source['channel_id'],
            q=source.get('keyword'),
            type="video",
            maxResults=50, # 增加結果數量以確保能找到指定月份的影片
            order="date",
            # 新增：傳入時間參數
            publishedAfter=published_after,
            publishedBefore=published_before
        )
        response = request.execute()

        for item in response.get('items', []):
            video_id = item['id']['videoId']
            if video_id not in processed_ids:
                title = item['snippet']['title']
                print(f"發現新影片: {title}")
                transcript = get_youtube_transcript(video_id)
                if transcript:
                    yield {'id': video_id, 'title': title, 'url': f"https://www.youtube.com/watch?v={video_id}", 'content': transcript}
                else:
                    save_processed_id(video_id)
                    print(f"無法取得 '{title}' 的逐字稿，已略過。\n")
    except Exception as e:
        print(f"檢查 YouTube 頻道 '{source['name']}' 時出錯: {e}")

def check_rss_feed(source, processed_ids, year=None, month=None):
    """檢查單個 RSS Feed，支援時間過濾"""
    print(f"--- 正在檢查 RSS Feed: {source['name']} ---")
    try:
        feed = feedparser.parse(source['url'])
        if year and month:
            print(f"時間範圍過濾已啟用: {year}年{month}月")
            
        for entry in feed.entries:
            item_id = entry.get('id', entry.link)
            
            # 新增：時間過濾邏輯
            if year and month:
                if 'published_parsed' in entry:
                    entry_time = entry.published_parsed
                    if not (entry_time.tm_year == year and entry_time.tm_mon == month):
                        continue # 如果年月不符，跳過此篇文章
                else:
                    # 如果文章沒有提供發布時間，在時間過濾模式下直接跳過
                    continue
            
            if item_id not in processed_ids:
                title = entry.title
                print(f"發現新文章: {title}")
                article_text = get_article_text(entry.link)
                if article_text:
                    yield {'id': item_id, 'title': title, 'url': entry.link, 'content': article_text}
                else:
                    save_processed_id(item_id)
                    print(f"無法取得 '{title}' 的內文，已略過。\n")
    except Exception as e:
        print(f"檢查 RSS Feed '{source['name']}' 時出錯: {e}")

def main():
    """程式主進入點"""
    # 區塊 1.5: 指令列參數解析
    parser = argparse.ArgumentParser(description="自動化內容追蹤、摘要與通知工具")
    parser.add_argument("--year", type=int, help="要搜尋的年份 (例如: 2025)")
    parser.add_argument("--month", type=int, help="要搜尋的月份 (1-12)")
    args = parser.parse_args()

    # 檢查參數是否成對出現
    if (args.year and not args.month) or (not args.year and args.month):
        parser.error("--year 和 --month 必須同時提供。")
        return

    print(f"程式啟動於 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    config = load_config()
    if not config:
        return
        
    processed_ids = load_processed_ids()
    print(f"已載入 {len(processed_ids)} 個已處理項目 ID。")
    
    for source in config.get('sources', []):
        if not source.get('enabled', False):
            continue
            
        new_items = []
        if source['type'] == 'youtube':
            new_items = check_youtube_channel(source, config['YOUTUBE_API_KEY'], processed_ids, args.year, args.month)
        elif source['type'] == 'rss':
            new_items = check_rss_feed(source, processed_ids, args.year, args.month)
            
        for item in new_items:
            process_item(item['id'], item['title'], item['url'], item['content'], config)
            time.sleep(2)

    print(f"\n所有檢查完成於 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# ==============================================================================
# 區塊 6: 程式執行
# ==============================================================================
if __name__ == "__main__":
    main()