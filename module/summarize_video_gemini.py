import os
import argparse
import re
import google.generativeai as genai
from youtube_transcript_api import YouTubeTranscriptApi
from pytube import YouTube

# 匯入 Whisper 函式庫，並處理可能未安裝的情況
try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    print("警告：Whisper 函式庫未安裝，語音轉文字的備用方案將無法使用。")
    print("請執行: pip install git+https://github.com/openai/whisper.git")
    WHISPER_AVAILABLE = False


# --- 設定區 ---
# 從環境變數讀取 API 金鑰
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


def get_video_id(url):
    """從各種 YouTube URL 格式中解析出 video_id"""
    patterns = [
        r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/watch\?v=([a-zA-Z0-9_-]{11})',
        r'(?:https?:\/\/)?youtu\.be\/([a-zA-Z0-9_-]{11})',
        r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/shorts\/([a-zA-Z0-9_-]{11})'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_youtube_content(video_id):
    """
    (升級版) 根據 video_id 取得影片標題和逐字稿。
    Plan A: 嘗試抓取官方 CC 字幕。
    Plan B: 如果 Plan A 失敗，則下載音訊並使用 Whisper 進行語音轉文字。
    """
    try:
        # 使用 Pytube 獲取影片標題，這一步總需要執行
        yt = YouTube(f"https://www.youtube.com/watch?v={video_id}")
        title = yt.title
        transcript = None

        # --- Plan A: 嘗試抓取官方 CC 字幕 ---
        print("正在嘗試抓取官方字幕 (Plan A)...")
        try:
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['zh-TW', 'zh-Hant', 'en', 'zh-Hans'])
            transcript = " ".join([item['text'] for item in transcript_list])
            print("成功抓取官方字幕！")
        except Exception as e:
            print(f"Plan A 失敗：找不到官方字幕 ({e})。")
            transcript = None

        # --- Plan B: 如果 Plan A 失敗，啟動語音轉文字 ---
        if not transcript:
            print("正在啟動語音轉文字備用方案 (Plan B)...")
            if not WHISPER_AVAILABLE:
                raise Exception("Whisper 函式庫未安裝，無法執行 Plan B。")

            # 1. 下載音訊
            print("正在下載音訊...")
            audio_stream = yt.streams.filter(only_audio=True).first()
            temp_dir = "temp_audio"
            if not os.path.exists(temp_dir):
                os.makedirs(temp_dir)
            audio_file = audio_stream.download(output_path=temp_dir)
            
            # 2. 使用 Whisper 轉錄
            print("正在使用 Whisper 進行語音轉文字，這可能需要一些時間...")
            model = whisper.load_model("base") # "base" 模型速度快，效果不錯
            result = model.transcribe(audio_file)
            transcript = result['text']
            
            # 3. 清理暫存檔案
            os.remove(audio_file)
            print("Plan B 執行完畢！")

        return title, transcript

    except Exception as e:
        error_message = f"錯誤：處理影片 '{video_id}' 時發生無法恢復的錯誤。\n詳細原因: {e}"
        return None, error_message


def get_summary_from_gemini(content, api_key):
    """將內容傳送給 Gemini API 以獲取摘要"""
    if not api_key:
        return "錯誤：找不到 GEMINI_API_KEY。請確認已設定環境變數。"
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-pro')
        prompt = f"""
        請扮演一位專業的內容分析師。
        請將以下的 YouTube 影片逐字稿，整理成一份清晰、易於理解的條列式重點摘要（3到5點）。
        摘要需使用繁體中文。
        --- 逐字稿開始 ---
        {content}
        --- 逐字稿結束 ---
        重點摘要：
        """
        print("\n正在呼叫 AI 產生摘要，請稍候...")
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"錯誤：呼叫 Gemini API 失敗。詳細原因: {e}"

def main():
    """程式主進入點"""
    parser = argparse.ArgumentParser(description="輸入一個 YouTube 影片網址，產生影片的 AI 摘要。")
    parser.add_argument("video_url", type=str, help="要進行摘要的 YouTube 影片網址。")
    args = parser.parse_args()

    video_id = get_video_id(args.video_url)
    if not video_id:
        print("錯誤：無法從輸入的網址中解析出有效的 YouTube Video ID。")
        return

    print(f"正在處理影片 ID: {video_id}")
    
    title, content = get_youtube_content(video_id)

    if title and content: # 成功獲取到標題和內容
        summary = get_summary_from_gemini(content, GEMINI_API_KEY)
        
        print("\n==================================================")
        print(f"影片標題： {title}")
        print("==================================================")
        print("\n--- AI 重點摘要 ---\n")
        print(summary)
        print("\n-------------------\n")
        # 如果需要，可以取消下一行的註解來顯示完整逐字稿
        # print(f"\n--- 完整逐字稿 ---\n\n{content}")
        print("==================================================")
    else: # 如果 get_youtube_content 回傳了錯誤訊息
        print(f"\n處理失敗：{content}")

if __name__ == "__main__":
    main()