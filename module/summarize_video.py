import os
import argparse
import re
import importlib
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional, Tuple

import google.generativeai as genai
from youtube_transcript_api import YouTubeTranscriptApi
from pytube import YouTube

# --- 設定區 ---
# 從環境變數讀取 API 金鑰
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
WHISPER_MODEL_NAME = os.getenv("WHISPER_MODEL", "base")
_WHISPER_MODEL = None
_WHISPER_IMPORT_FAILED = False

def get_video_id(url):
    """從各種 YouTube URL 格式中解析出 video_id"""
    # 正則表達式，匹配各種 YouTube 網址
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

def _load_whisper_model():
    """載入 Whisper 模型（若可用）。"""
    global _WHISPER_MODEL, _WHISPER_IMPORT_FAILED

    if _WHISPER_MODEL is not None:
        return _WHISPER_MODEL

    if _WHISPER_IMPORT_FAILED:
        return None

    try:
        whisper_module = importlib.import_module("whisper")
    except ImportError:
        print("警告：未安裝 whisper 套件，無法使用離線語音轉文字備援。")
        _WHISPER_IMPORT_FAILED = True
        return None

    try:
        _WHISPER_MODEL = whisper_module.load_model(WHISPER_MODEL_NAME)
    except Exception as exc:
        print(f"警告：Whisper 模型載入失敗（{exc}），無法使用離線語音轉文字備援。")
        _WHISPER_IMPORT_FAILED = True
        return None

    return _WHISPER_MODEL


def _download_audio_with_ytdlp(video_url: str, download_dir: Path) -> Optional[Path]:
    """使用 yt-dlp 下載影片的音訊檔。"""
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        print("警告：未安裝 yt-dlp 套件，無法下載音訊。")
        return None

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(download_dir / "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            video_id = info.get("id")
    except Exception as exc:
        print(f"警告：下載音訊失敗（{exc}）。")
        return None

    if not video_id:
        return None

    audio_path = download_dir / f"{video_id}.mp3"
    if audio_path.exists():
        return audio_path

    # 若後處理產生不同副檔名，嘗試尋找其他檔案
    for candidate in download_dir.glob(f"{video_id}.*"):
        if candidate.is_file():
            return candidate

    return None


def _transcribe_audio(audio_path: Path) -> Optional[str]:
    """利用 Whisper 將音訊檔轉為文字。"""
    model = _load_whisper_model()
    if model is None:
        return None

    try:
        result = model.transcribe(str(audio_path))
        text = result.get("text", "")
    except Exception as exc:
        print(f"警告：Whisper 轉寫失敗（{exc}）。")
        return None

    return text.strip() or None


def _transcribe_with_offline_fallback(video_id: str) -> Optional[str]:
    """當無法取得官方逐字稿時，改以下載音訊並離線轉寫。"""
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    with TemporaryDirectory() as tmp_dir:
        audio_path = _download_audio_with_ytdlp(video_url, Path(tmp_dir))
        if not audio_path:
            return None

        return _transcribe_audio(audio_path)


def get_youtube_content(video_id: str) -> Tuple[Optional[str], Optional[str]]:
    """根據 video_id 取得影片標題和逐字稿，必要時使用離線備援。"""
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    try:
        yt = YouTube(video_url)
        title = yt.title
    except Exception as exc:
        print(f"錯誤：無法獲取影片 '{video_id}' 的標題。詳細原因: {exc}")
        title = None

    transcript = None

    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(
            video_id, languages=['zh-TW', 'zh-Hant', 'en', 'zh-Hans']
        )
        transcript = " ".join(item['text'] for item in transcript_list)
    except Exception as exc:
        print(f"警告：官方字幕取得失敗，改用離線語音轉文字備援。詳細原因: {exc}")

    if transcript:
        return title, transcript

    fallback_transcript = _transcribe_with_offline_fallback(video_id)
    if fallback_transcript:
        return title, fallback_transcript

    print(f"錯誤：無法取得影片 '{video_id}' 的文字內容。")
    return title, None

def get_summary_from_gemini(content, api_key):
    """將內容傳送給 Gemini API 以獲取摘要"""
    if not api_key:
        return "錯誤：找不到 GEMINI_API_KEY。請確認已設定環境變數。"

    try:
        # 設定 Gemini API
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-pro')

        # 準備我們的指令 (Prompt)
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
    
    title, transcript = get_youtube_content(video_id)

    if transcript:
        summary = get_summary_from_gemini(transcript, GEMINI_API_KEY)
        
        print("\n==================================================")
        print(f"影片標題： {title}")
        print("==================================================")
        print("\n--- AI 重點摘要 ---\n")
        print(summary)
        print("\n-------------------\n")
        # print("\n--- 完整逐字稿 ---\n") # 如果需要，可以取消這一行的註解來顯示完整逐字稿
        # print(transcript)
        print("==================================================")

if __name__ == "__main__":
    main()
