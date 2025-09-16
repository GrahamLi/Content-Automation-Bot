import os
import argparse
import re
import importlib
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional, Tuple

import google.generativeai as genai
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)
from pytube import YouTube

# --- 設定區 ---
# 從環境變數讀取 API 金鑰
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
WHISPER_MODEL_NAME = os.getenv("WHISPER_MODEL", "base")
_WHISPER_MODEL = None
_WHISPER_IMPORT_FAILED = False


def get_youtube_content(video_id: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(
            video_id, languages=["zh-TW", "en"]
        )
        transcript = "\n".join(item["text"] for item in transcript_list)
        title = YouTube(f"https://www.youtube.com/watch?v={video_id}").title
        return title, transcript, None
    except Exception as e:
        return None, None, f"錯誤：無法獲取影片 '{video_id}' 的內容。詳細原因: {e}"


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
    
    title, transcript, error_message = get_youtube_content(video_id)

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
    elif error_message:
        print(error_message)

if __name__ == "__main__":
    main()
