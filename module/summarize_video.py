import os
import argparse
import re
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
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

# --- 設定區 ---
# 從環境變數讀取 API 金鑰
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
WHISPER_MODEL_NAME = os.getenv("WHISPER_MODEL", "base")
_WHISPER_MODEL = None
_WHISPER_IMPORT_FAILED = False


def get_youtube_content(video_id: str):
    try:
        title = YouTube(f"https://www.youtube.com/watch?v={video_id}").title
    except VideoUnavailable as e:
        return None, None, f"錯誤：無法存取影片 '{video_id}'。詳細原因: {e}"
    except Exception as e:
        return None, None, f"錯誤：無法載入影片 '{video_id}' 的資訊。詳細原因: {e}"

    try:
        transcripts = YouTubeTranscriptApi.list_transcripts(video_id)
        try:
            # Try native Chinese transcript first
            transcript = transcripts.find_transcript(['zh-Hant', 'zh-TW', 'zh-CN']).fetch()
        except NoTranscriptFound:
            # Try to translate an existing transcript into Chinese
            transcript = (transcripts.find_transcript(['en', 'ja', 'auto'])
                           .translate('zh-Hant')
                           .fetch())
        text = "\n".join(item["text"] for item in transcript)
        return title, text, None
    except (NoTranscriptFound, TranscriptsDisabled) as transcript_error:
        print(
            f"偵測到官方字幕不可用（{transcript_error}），改用 yt-dlp + Whisper 進行備援轉錄..."
        )
        transcript_text, fallback_error = generate_transcript_with_whisper(video_id)
        if transcript_text:
            return title, transcript_text, None
        error_message = (
            "錯誤：影片沒有可用字幕，且備援語音轉文字流程失敗。"
            f" 原始錯誤: {transcript_error}; 備援錯誤: {fallback_error}"
        )
        return title, None, error_message
    except Exception as e:
        return title, None, f"錯誤：無法獲取影片 '{video_id}' 的內容。詳細原因: {e}"

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


def load_whisper_model():
    """Lazy-load Whisper 模型，避免在未安裝時崩潰"""
    global _WHISPER_MODEL, _WHISPER_IMPORT_FAILED

    if _WHISPER_MODEL is not None:
        return _WHISPER_MODEL

    if _WHISPER_IMPORT_FAILED:
        raise RuntimeError("Whisper 模組先前載入失敗，請確認已安裝 openai-whisper。")

    try:
        import whisper  # type: ignore
    except ImportError as exc:  # pragma: no cover - 依賴於外部環境
        _WHISPER_IMPORT_FAILED = True
        raise RuntimeError(
            "Whisper 模組未安裝。請執行 `pip install openai-whisper`。"
        ) from exc

    try:
        _WHISPER_MODEL = whisper.load_model(WHISPER_MODEL_NAME)
    except Exception as exc:  # pragma: no cover - 實際錯誤依環境而定
        _WHISPER_IMPORT_FAILED = True
        raise RuntimeError(f"Whisper 模型載入失敗：{exc}") from exc

    return _WHISPER_MODEL


def download_audio_with_ytdlp(video_id: str, output_dir: Path) -> Path:
    """使用 yt-dlp 下載指定影片的最佳音訊"""
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    options = {
        "format": "bestaudio/best",
        "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with YoutubeDL(options) as ydl:
            ydl.download([video_url])
    except DownloadError as exc:
        raise RuntimeError(f"yt-dlp 下載音訊失敗：{exc}") from exc

    downloaded_files = list(output_dir.glob(f"{video_id}.*"))
    if not downloaded_files:
        raise RuntimeError("yt-dlp 下載完成，但找不到音訊檔案。")

    return downloaded_files[0]


def transcribe_audio_with_whisper(audio_path: Path) -> str:
    """使用 Whisper 對音訊檔進行轉錄"""
    model = load_whisper_model()
    result = model.transcribe(str(audio_path))
    text = result.get("text", "").strip()
    if not text:
        raise RuntimeError("Whisper 未能產生有效的逐字稿。")
    return text


def generate_transcript_with_whisper(video_id: str) -> Tuple[Optional[str], Optional[str]]:
    """利用 yt-dlp + Whisper 取得影片的備援逐字稿"""
    try:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            audio_file = download_audio_with_ytdlp(video_id, tmp_path)
            transcript_text = transcribe_audio_with_whisper(audio_file)
            return transcript_text, None
    except Exception as exc:
        return None, str(exc)

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
