import os
import argparse
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional, Tuple

import google.generativeai as genai
from youtube_transcript_api import YouTubeTranscriptApi
from pytube import YouTube
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

_WHISPER_MODEL = None
_WHISPER_IMPORT_FAILED = False
WHISPER_MODEL_NAME = "base"

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
            model = whisper.load_model(WHISPER_MODEL_NAME)  # 使用預設 Whisper 模型
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


def download_audio_with_ytdlp(
    video_id: str, output_dir: Path
) -> Tuple[Optional[Path], Optional[str]]:
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
        return None, f"yt-dlp 下載音訊失敗：{exc}"
    except Exception as exc:  # pragma: no cover - 依賴於外部工具
        return None, f"yt-dlp 下載音訊時發生未預期的錯誤：{exc}"

    downloaded_files = list(output_dir.glob(f"{video_id}.*"))
    if not downloaded_files:
        return None, "yt-dlp 下載完成，但找不到音訊檔案。"

    return downloaded_files[0], None


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
            audio_file, download_error = download_audio_with_ytdlp(video_id, tmp_path)
            if download_error:
                return None, download_error
            if audio_file is None:  # 型別保險，理論上不會發生
                return None, "yt-dlp 未傳回音訊檔案。"

            try:
                transcript_text = transcribe_audio_with_whisper(audio_file)
            except Exception as exc:  # pragma: no cover - 依環境而定
                return None, str(exc)

            return transcript_text, None
    except Exception as exc:  # pragma: no cover - 建立暫存目錄失敗等
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