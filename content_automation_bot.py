import youtube_transcript_api
import inspect
# DEBUG: 下方這行可以在遇到奇怪的 import 問題時取消註解
# print(f"DEBUG: Loading youtube_transcript_api from: {inspect.getfile(youtube_transcript_api)}")
# ==============================================================================
# 區塊 1: 匯入所有必要的函式庫
# ==============================================================================
import json
import os
import requests
import feedparser
import time
import argparse
import random
import urllib.parse
from datetime import datetime, timezone, timedelta

from googleapiclient.discovery import build
# 修正：使用別名匯入以避免名稱衝突
from youtube_transcript_api import YouTubeTranscriptApi as TranscriptAPI
from pytube import YouTube
from bs4 import BeautifulSoup

# 下載器備援：優先使用 yt-dlp，其次 pytube
try:
    from yt_dlp import YoutubeDL
    YTDLP_AVAILABLE = True
except Exception:
    YTDLP_AVAILABLE = False

# 語音轉文字的 Whisper 函式庫（暫時禁用以節省空間）
WHISPER_AVAILABLE = False
print("注意：為節省磁盤空間，Whisper 語音轉文字功能暫時禁用。")

# ==============================================================================
# 區塊 2: 設定與輔助函式
# ==============================================================================

# 用戶代理輪換列表
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/91.0.864.59'
]


def get_random_user_agent():
    """隨機選擇一個用戶代理"""
    return random.choice(USER_AGENTS)


def create_session_with_retry():
    """創建帶有重試機制的 requests session"""
    session = requests.Session()
    session.headers.update({
        'User-Agent': get_random_user_agent(),
        'Accept':
        'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    })
    return session


def smart_delay(min_delay=1.0, max_delay=3.0):
    """智能延遲，隨機化請求間隔"""
    delay = random.uniform(min_delay, max_delay)
    time.sleep(delay)


def load_config():
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("錯誤：找不到 config.json 檔案。")
        return None
    except json.JSONDecodeError:
        print("錯誤：config.json 格式不正確。")
        return None


# --- ID 管理 --- #
PROCESSED_IDS_FILE = 'processed_ids.txt'
FAILED_IDS_FILE = 'failed_ids.txt'


def load_ids_from_file(filename):
    """從給定的檔案載入 ID 集合"""
    if not os.path.exists(filename):
        return set()
    with open(filename, 'r', encoding='utf-8') as f:
        return set(line.strip() for line in f)


def save_id_to_file(item_id, filename):
    """將單一 ID 儲存到給定的檔案"""
    with open(filename, 'a', encoding='utf-8') as f:
        f.write(f"{item_id}\n")


def remove_id_from_file(item_id, filename):
    """從給定的檔案中移除一個 ID"""
    ids = load_ids_from_file(filename)
    if item_id in ids:
        ids.remove(item_id)
        with open(filename, 'w', encoding='utf-8') as f:
            for an_id in ids:
                f.write(f"{an_id}\n")


# ==============================================================================
# 區塊 3: 內容獲取與處理函式 - 改進版
# ==============================================================================


def get_youtube_transcript_improved(video_id, max_retries=3):
    """改進的 YouTube 字幕獲取功能，具備更好的錯誤處理"""
    for attempt in range(max_retries):
        try:
            # 添加隨機延遲避免被封鎖
            if attempt > 0:
                smart_delay(2, 5)
                print(f"重試第 {attempt + 1} 次獲取字幕...")

            # 嘗試使用 YouTubeTranscriptApi
            transcript_list = TranscriptAPI.get_transcript(
                video_id, languages=['zh-TW', 'zh-Hant', 'zh-CN', 'zh', 'en'])
            return " ".join([item['text'] for item in transcript_list])

        except Exception as e:
            error_msg = str(e).lower()
            print(
                f"影片 {video_id} 字幕獲取失敗 (嘗試 {attempt + 1}/{max_retries}): {e}")

            # 如果是特定錯誤，不要重試
            if any(keyword in error_msg for keyword in
                   ['disabled', 'not available', 'no transcript']):
                print(f"影片 {video_id} 字幕已被禁用或不存在，跳過重試")
                break

    return None


def get_youtube_transcript_improved_v2(video_id, max_retries=3):
    """Robust transcript retrieval with compatibility fallback.
    1) Try TranscriptAPI.get_transcript.
    2) Fallback to list_transcripts().find_transcript(...).fetch().
    3) Retry with small delays; stop on non-retriable errors.
    """
    preferred_langs = ['zh-TW', 'zh-Hant', 'zh-CN', 'zh', 'en']

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                smart_delay(2, 5)
                print(f"重試第 {attempt + 1} 次獲取字幕...")

            transcript_list = None

            try:
                # Primary path (common API)
                transcript_list = TranscriptAPI.get_transcript(
                    video_id, languages=preferred_langs)
            except AttributeError:
                # Compatibility paths (older/different versions)
                # A) list_transcripts API
                try:
                    transcripts = TranscriptAPI.list_transcripts(video_id)

                    # Try per-language match first
                    for lang in preferred_langs:
                        try:
                            t = transcripts.find_transcript([lang])
                            transcript_list = t.fetch()
                            break
                        except Exception:
                            continue

                    # Then try manual or generated across preferred langs
                    if transcript_list is None:
                        try:
                            t = transcripts.find_manually_created_transcript(
                                preferred_langs)
                            transcript_list = t.fetch()
                        except Exception:
                            try:
                                t = transcripts.find_generated_transcript(
                                    preferred_langs)
                                transcript_list = t.fetch()
                            except Exception:
                                pass
                except AttributeError:
                    # B) get_transcripts API (batch)
                    try:
                        transcripts_map, _errors = TranscriptAPI.get_transcripts(
                            [video_id], languages=preferred_langs)
                        tl = transcripts_map.get(video_id)
                        if tl:
                            transcript_list = tl
                    except Exception:
                        pass

            if transcript_list:
                return " ".join(item.get('text', '') for item in transcript_list)

            raise RuntimeError("no transcript found via available methods")

        except Exception as e:
            msg = str(e).lower()
            print(f"影片 {video_id} 字幕獲取失敗 (嘗試 {attempt + 1}/{max_retries}): {e}")
            if any(k in msg for k in [
                    'disabled', 'not available', 'no transcript', 'private',
                    'unavailable', 'not found'
            ]):
                print(f"影片 {video_id} 字幕已被禁用或不存在，跳過重試")
                break

    return None


def download_audio_with_enhanced_ytdlp(video_id,
                                       cookies_file=None,
                                       max_retries=3):
    """增強的 yt-dlp 音訊下載功能"""
    if not YTDLP_AVAILABLE:
        return None

    url = f"https://www.youtube.com/watch?v={video_id}"
    out_dir = "temp_audio"
    os.makedirs(out_dir, exist_ok=True)

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                smart_delay(3, 8)
                print(f"重試第 {attempt + 1} 次下載音訊...")

            # 更完整的 yt-dlp 選項
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(out_dir, f'{video_id}.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'noplaylist': True,
                'extract_flat': False,
                'writethumbnail': False,
                'writeinfojson': False,
                'user_agent': get_random_user_agent(),
                'http_headers': {
                    'Accept':
                    'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-us,en;q=0.5',
                    'Accept-Encoding': 'gzip,deflate',
                    'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.7',
                    'Connection': 'keep-alive',
                }
            }

            if cookies_file and os.path.exists(cookies_file):
                ydl_opts['cookiefile'] = cookies_file

            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                ext = info.get('ext', 'm4a')
                file_path = os.path.join(out_dir, f'{video_id}.{ext}')

                if os.path.exists(file_path):
                    return file_path

                # 嘗試找到下載的檔案
                for filename in os.listdir(out_dir):
                    if filename.startswith(video_id):
                        return os.path.join(out_dir, filename)

        except Exception as e:
            error_msg = str(e).lower()
            print(f"yt-dlp 下載失敗 (嘗試 {attempt + 1}/{max_retries}): {e}")

            # 某些錯誤不值得重試
            if any(keyword in error_msg
                   for keyword in ['private', 'unavailable', 'not found']):
                print(f"影片 {video_id} 不可用，跳過重試")
                break

    return None


def download_audio_with_enhanced_pytube(video_id, max_retries=3):
    """增強的 pytube 音訊下載功能"""
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                smart_delay(2, 5)
                print(f"使用 pytube 重試第 {attempt + 1} 次...")

            yt = YouTube(f"https://www.youtube.com/watch?v={video_id}",
                         use_oauth=False,
                         allow_oauth_cache=False)

            # 嘗試獲取最佳音訊流
            audio_stream = yt.streams.filter(only_audio=True,
                                             file_extension='mp4').first()
            if not audio_stream:
                audio_stream = yt.streams.filter(only_audio=True).first()

            if audio_stream:
                out_dir = "temp_audio"
                os.makedirs(out_dir, exist_ok=True)
                return audio_stream.download(output_path=out_dir)

        except Exception as e:
            print(f"pytube 下載失敗 (嘗試 {attempt + 1}/{max_retries}): {e}")

    return None


def transcribe_with_whisper(audio_file, model_size="base"):
    """使用 Whisper 進行語音轉文字（目前禁用）"""
    print("Whisper 功能已禁用以節省磁盤空間")
    # 清理音訊檔案
    try:
        if audio_file and os.path.exists(audio_file):
            os.remove(audio_file)
    except Exception:
        pass
    return None


def get_youtube_transcript_with_fallback(video_id,
                                         verbose=False,
                                         max_retries=3):
    """完整的備援字幕獲取系統"""
    print(f"正在處理影片: {video_id}")

    # 第一步：嘗試獲取現有字幕
    transcript = get_youtube_transcript_improved_v2(video_id, max_retries)
    if transcript:
        print(f"成功獲取影片 {video_id} 的字幕")
        return transcript

    print(f"影片 {video_id} 無法獲取字幕，嘗試語音轉文字...")

    if not WHISPER_AVAILABLE:
        print("Whisper 未安裝，無法進行語音轉文字")
        return None

    # 從 config 讀取設定
    cookies_file = None
    try:
        cfg = load_config() or {}
        cookies_file = cfg.get('cookies_file')
    except Exception:
        pass

    # 第二步：嘗試使用 yt-dlp 下載音訊
    audio_file = download_audio_with_enhanced_ytdlp(video_id, cookies_file,
                                                    max_retries)

    # 第三步：如果 yt-dlp 失敗，嘗試 pytube
    if not audio_file:
        print("yt-dlp 下載失敗，嘗試使用 pytube...")
        audio_file = download_audio_with_enhanced_pytube(video_id, max_retries)

    # 第四步：使用 Whisper 轉錄
    if audio_file:
        transcript = transcribe_with_whisper(audio_file)
        if transcript:
            print(f"成功通過語音轉文字獲取影片 {video_id} 的內容")
            return transcript

    print(f"影片 {video_id} 所有方法都失敗了")
    return None


def get_article_text(url, max_retries=3):
    """改進的文章文本獲取功能"""
    session = create_session_with_retry()

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                smart_delay(1, 3)
                print(f"重試第 {attempt + 1} 次獲取文章...")

            response = session.get(url, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # 嘗試多種方式提取文章內容
            content_selectors = [
                'article', 'main', '.content', '.post-content',
                '.entry-content', '#content', '.article-body'
            ]

            article_body = None
            for selector in content_selectors:
                article_body = soup.select_one(selector)
                if article_body:
                    break

            if article_body:
                paragraphs = article_body.find_all('p')
                text = "\n".join([
                    p.get_text().strip() for p in paragraphs
                    if p.get_text().strip()
                ])
                return text if text else "無法提取有效文章內容"
            else:
                return "無法自動提取文章主體，請查看原始網頁。"

        except Exception as e:
            print(f"讀取文章失敗 (嘗試 {attempt + 1}/{max_retries}): {e}")

    return None


def get_summary_from_llm(content, api_key):
    """將內容傳送給 Google Gemini API 以獲取摘要"""
    print("正在透過 Gemini API 產生摘要...")
    if not api_key or "請在這裡" in api_key:
        return "摘要功能未設定：請在 config.json 中提供有效的 LLM_API_KEY。"

    try:
        import google.generativeai as genai
    except ImportError:
        return "錯誤：`google-generativeai` 函式庫未安裝。請執行 `pip install -r requirements.txt`。"

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-pro')

        prompt = ("您是一位專業的財經內容分析師。請根據以下逐字稿，提供一份詳細、專業、點列式的摘要，並使用繁體中文（台灣）。"
                  "摘要應包含至少三個關鍵要點，並總結影片的核心觀點。\n\n"
                  "--- 以下為逐字稿 ---\n"
                  f"{content}")

        response = model.generate_content(prompt)

        if response.text:
            return response.text
        else:
            if response.prompt_feedback:
                print(f"警告：Gemini 內容生成可能被阻擋。原因: {response.prompt_feedback}")
            return "無法從 Gemini 獲取摘要，可能因為內容安全設定或 API 問題。"

    except Exception as e:
        print(f"呼叫 Gemini API 時發生錯誤: {e}")
        return f"呼叫 Gemini API 失敗: {e}"


# ==============================================================================
# 區塊 4: 輸出與通知函式
# ==============================================================================


def broadcast_line_message(access_token, message):
    if not access_token or "請在這裡" in access_token:
        print("未設定 LINE Channel Access Token，略過發送。")
        return
    url = "https://api.line.me/v2/bot/message/broadcast"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}"
    }
    data = {"messages": [{"type": "text", "text": message}]}
    try:
        response = requests.post(url,
                                 headers=headers,
                                 data=json.dumps(data),
                                 timeout=30)
        if response.status_code == 200:
            print("廣播訊息已成功發送。")
        else:
            print(f"LINE 廣播訊息發送失敗: {response.status_code} {response.text}")
    except Exception as e:
        print(f"LINE 廣播訊息發送時發生錯誤: {e}")


def save_to_markdown(title, url, summary, content):
    if not os.path.exists('output'):
        os.makedirs('output')
    safe_title = "".join(c for c in title
                         if c.isalnum() or c in (' ', '-', '_')).rstrip()
    filename = f"output/{datetime.now().strftime('%Y%m%d')}_{safe_title}.md"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(f"# {title}\n\n**來源網址:** [{url}]({url})\n\n---\n\n")
        summary_formatted = summary.replace('\n', '\n\n')
        f.write(f"## 重點摘要\n\n{summary_formatted}\n\n---\n\n")
        content_formatted = content.replace('\n', '\n\n')
        f.write(f"## 全文/逐字稿\n\n{content_formatted}")
    print(f"內容已儲存至: {filename}")


# ==============================================================================
# 區塊 5: 主流程與檢查器
# ==============================================================================


def process_item(item_id, title, url, content, config):
    summary = get_summary_from_llm(content, config.get("LLM_API_KEY"))
    line_message = f"【新內容廣播】\n\n標題：{title}\n網址：{url}\n\n摘要：\n{summary}"
    broadcast_line_message(config.get("LINE_CHANNEL_ACCESS_TOKEN"),
                           line_message)
    save_to_markdown(title, url, summary, content)
    # 處理成功，寫入 processed_ids.txt 並從 failed_ids.txt 移除
    save_id_to_file(item_id, PROCESSED_IDS_FILE)
    remove_id_from_file(item_id, FAILED_IDS_FILE)
    print(f"已成功處理並廣播項目: {title}\n")


def check_youtube_channel(source,
                          api_key,
                          processed_ids,
                          failed_ids,
                          year=None,
                          month=None,
                          date=None):
    """檢查單個 YouTube 頻道，支援到「日」的精確時間過濾"""
    print(f"--- 正在檢查 YouTube 頻道: {source['name']} ---")
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        published_after = None
        published_before = None

        if year and month:
            if date:
                start_time = datetime(year,
                                      month,
                                      date,
                                      0,
                                      0,
                                      0,
                                      tzinfo=timezone.utc)
                end_time = start_time + timedelta(days=1)
            else:
                start_time = datetime(year,
                                      month,
                                      1,
                                      0,
                                      0,
                                      0,
                                      tzinfo=timezone.utc)
                if month == 12:
                    end_time = datetime(year + 1,
                                        1,
                                        1,
                                        0,
                                        0,
                                        0,
                                        tzinfo=timezone.utc)
                else:
                    end_time = datetime(year,
                                        month + 1,
                                        1,
                                        0,
                                        0,
                                        0,
                                        tzinfo=timezone.utc)

            published_after = start_time.isoformat()
            published_before = end_time.isoformat()
            print(f"時間範圍過濾已啟用: 從 {published_after} 到 {published_before}")

        request = youtube.search().list(part="snippet",
                                        channelId=source['channel_id'],
                                        q=source.get('keyword'),
                                        type="video",
                                        maxResults=50,
                                        order="date",
                                        publishedAfter=published_after,
                                        publishedBefore=published_before)
        response = request.execute()

        for item in response.get('items', []):
            video_id = item['id']['videoId']
            if video_id in processed_ids:
                continue  # 成功處理過的，永久跳過

            title = item['snippet']['title']
            print(f"發現新影片: {title}" +
                  (" (重試中...)" if video_id in failed_ids else ""))

            # 使用改進的字幕獲取功能
            transcript = get_youtube_transcript_with_fallback(video_id)

            if transcript:
                yield {
                    'id': video_id,
                    'title': title,
                    'url': f"https://www.youtube.com/watch?v={video_id}",
                    'content': transcript
                }
            else:
                # 失敗則寫入 failed_ids.txt
                save_id_to_file(video_id, FAILED_IDS_FILE)
                print(f"無法取得 '{title}' 的逐字稿，已標記為失敗並將於下次重試。\n")

            # 在處理每個影片之間添加延遲
            smart_delay(1, 3)

    except Exception as e:
        print(f"檢查 YouTube 頻道 '{source['name']}' 時出錯: {e}")


def check_rss_feed(source,
                   processed_ids,
                   failed_ids,
                   year=None,
                   month=None,
                   date=None):
    """檢查單個 RSS Feed，支援到「日」的精確時間過濾"""
    print(f"--- 正在檢查 RSS Feed: {source['name']} ---")
    try:
        feed = feedparser.parse(source['url'])
        if year and month:
            date_str = f"{year}年{month}月" + (f"{date}日" if date else "")
            print(f"時間範圍過濾已啟用: {date_str}")

        for entry in feed.entries:
            item_id = entry.get('id', entry.link)
            if item_id in processed_ids:
                continue  # 成功處理過的，永久跳過

            # 時間過濾邏輯
            if year and month and 'published_parsed' in entry:
                entry_time = entry.published_parsed
                if not (entry_time.tm_year == year
                        and entry_time.tm_mon == month):
                    continue
                if date and not (entry_time.tm_mday == date):
                    continue
            elif year and month:
                continue

            title = entry.title
            print(f"發現新文章: {title}" +
                  (" (重試中...)" if item_id in failed_ids else ""))
            article_text = get_article_text(entry.link)

            if article_text:
                yield {
                    'id': item_id,
                    'title': title,
                    'url': entry.link,
                    'content': article_text
                }
            else:
                # 失敗則寫入 failed_ids.txt
                save_id_to_file(item_id, FAILED_IDS_FILE)
                print(f"無法取得 '{title}' 的內文，已標記為失敗並將於下次重試。\n")

            # 在處理每篇文章之間添加延遲
            smart_delay(0.5, 1.5)

    except Exception as e:
        print(f"檢查 RSS Feed '{source['name']}' 時出錯: {e}")


def main():
    """程式主進入點"""
    parser = argparse.ArgumentParser(description="自動化內容追蹤、摘要與通知工具")
    parser.add_argument("--year", type=int, help="要搜尋的年份 (例如: 2025)")
    parser.add_argument("--month", type=int, help="要搜尋的月份 (1-12)")
    parser.add_argument("--date",
                        type=int,
                        help="要搜尋的日期 (1-31)，必須與 --year 和 --month 一起使用")
    args = parser.parse_args()

    if args.date and not (args.year and args.month):
        parser.error("--date 參數必須與 --year 和 --month 同時使用。")
    elif (args.year and not args.month) or (not args.year and args.month):
        parser.error("--year 和 --month 必須同時提供。")

    print(f"程式啟動於 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    config = load_config()
    if not config: return

    processed_ids = load_ids_from_file(PROCESSED_IDS_FILE)
    failed_ids = load_ids_from_file(FAILED_IDS_FILE)
    print(f"已載入 {len(processed_ids)} 個已處理項目 ID。")
    print(f"已載入 {len(failed_ids)} 個先前失敗的項目 ID，將會重試。")

    for source in config.get('sources', []):
        if not source.get('enabled', False): continue

        new_items = []
        if source['type'] == 'youtube':
            new_items = check_youtube_channel(source,
                                              config['YOUTUBE_API_KEY'],
                                              processed_ids, failed_ids,
                                              args.year, args.month, args.date)
        elif source['type'] == 'rss':
            new_items = check_rss_feed(source, processed_ids, failed_ids,
                                       args.year, args.month, args.date)

        for item in new_items:
            process_item(item['id'], item['title'], item['url'],
                         item['content'], config)
            smart_delay(2.0, 4.0)  # 處理項目之間的延遲

    print(f"\n所有檢查完成於 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


# ==============================================================================
# 區塊 6: 程式執行
# ==============================================================================
if __name__ == "__main__":
    main()
