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

WHISPER_MODEL_NAME = os.getenv("WHISPER_MODEL_NAME", "base")
_WHISPER_MODEL: Optional["whisper.Whisper"] = None
_WHISPER_IMPORT_FAILED = False


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


def _fetch_video_title(video_id: str) -> Optional[str]:
    """使用 pytube 取得影片標題，失敗時回傳 None。"""

    try:
        yt = YouTube(f"https://www.youtube.com/watch?v={video_id}")
        return yt.title
    except Exception:
        return None


def _call_transcript_method(owner: object, method_name: str, *args):
    """呼叫字幕 API 的方法，並處理補齊 self 的需求。"""

    try:
        method = getattr(owner, method_name)
    except AttributeError:
        return None

    if not callable(method):
        return None

    try:
        return method(*args)
    except AssertionError:
        return None
    except TypeError as exc:
        if "positional argument" not in str(exc) or not isinstance(owner, type):
            raise
        try:
            instance = owner()
        except Exception as inst_exc:  # pragma: no cover - 取決於底層實作
            raise exc from inst_exc
        bound_method = getattr(instance, method_name, None)
        if not callable(bound_method):
            raise exc
        try:
            return bound_method(*args)
        except AssertionError:
            return None


def _list_transcripts_for_video(video_id: str):
    """嘗試以各種方式列出影片的字幕清單。"""

    transcripts = _call_transcript_method(YouTubeTranscriptApi, "list_transcripts", video_id)
    if transcripts is not None:
        return transcripts

    transcripts = _call_transcript_method(YouTubeTranscriptApi, "list", video_id)
    if transcripts is not None:
        return transcripts

    return None


def _probe_transcript_errors(
    video_id: str,
) -> Optional[Tuple[Optional[str], Optional[str], Optional[str]]]:
    """使用 fetch 類方法觸發例外，以取得使用者友善訊息。"""

    for method_name in ("get_transcript", "fetch"):
        try:
            result = _call_transcript_method(
                YouTubeTranscriptApi,
                method_name,
                video_id,
                ['zh-Hant', 'zh-TW', 'zh-CN'],
            )
        except TranscriptsDisabled:
            title = _fetch_video_title(video_id)
            return title, None, "這支影片的字幕已被停用，無法取得逐字稿。"
        except VideoUnavailable:
            return None, None, "影片不存在或已移除，無法取得逐字稿。"
        except NoTranscriptFound:
            title = _fetch_video_title(video_id)
            return title, None, "影片沒有提供任何字幕，無法取得逐字稿。"
        except Exception as exc:  # pragma: no cover - 非預期例外
            error_message = (
                f"錯誤：處理影片 '{video_id}' 時發生無法恢復的錯誤。\n詳細原因: {exc}"
            )
            return None, None, error_message

        if result:
            transcript_text = " ".join(
                entry.get("text", "") for entry in result if isinstance(entry, dict)
            ).strip()
            if transcript_text:
                title = _fetch_video_title(video_id)
                return title, transcript_text, None

    return None

def get_youtube_content(video_id: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """嘗試取得指定影片的標題與官方字幕內容。"""

    try:
        transcripts = _list_transcripts_for_video(video_id)
    except TranscriptsDisabled:
        title = _fetch_video_title(video_id)
        return title, None, "這支影片的字幕已被停用，無法取得逐字稿。"
    except VideoUnavailable:
        return None, None, "影片不存在或已移除，無法取得逐字稿。"
    except NoTranscriptFound:
        title = _fetch_video_title(video_id)
        return title, None, "影片沒有提供任何字幕，無法取得逐字稿。"
    except Exception as exc:
        error_message = (
            f"錯誤：處理影片 '{video_id}' 時發生無法恢復的錯誤。\n詳細原因: {exc}"
        )
        return None, None, error_message

    if transcripts is None:
        probe_result = _probe_transcript_errors(video_id)
        if probe_result is not None:
            return probe_result

        title = _fetch_video_title(video_id)
        return title, None, "影片沒有提供任何字幕，無法取得逐字稿。"

    title = _fetch_video_title(video_id)
    transcript_obj = None

    try:
        transcript_obj = transcripts.find_transcript(['zh-Hant', 'zh-TW', 'zh-CN'])
    except NoTranscriptFound:
        available_languages = []
        for transcript in transcripts:
            language_code = getattr(transcript, "language_code", None) or getattr(
                transcript, "language", ""
            )
            if language_code and language_code not in available_languages:
                available_languages.append(language_code)

            if transcript_obj is None and getattr(transcript, "is_translatable", False):
                try:
                    transcript_obj = transcript.translate('zh-Hant')
                    break
                except NoTranscriptFound:
                    continue

        if transcript_obj is None:
            if available_languages:
                languages_text = ", ".join(available_languages)
                message = (
                    "影片僅提供以下語言的字幕，且無法翻譯成繁體中文： "
                    f"{languages_text}。"
                )
            else:
                message = "影片沒有提供任何字幕，無法取得逐字稿。"
            return title, None, message
    except TranscriptsDisabled:
        return title, None, "這支影片的字幕已被停用，無法取得逐字稿。"
    except VideoUnavailable:
        return None, None, "影片不存在或已移除，無法取得逐字稿。"
    except Exception as exc:
        error_message = (
            f"錯誤：處理影片 '{video_id}' 時發生無法恢復的錯誤。\n詳細原因: {exc}"
        )
        return title, None, error_message

    try:
        transcript_entries = transcript_obj.fetch()
    except Exception as exc:
        error_message = (
            f"錯誤：處理影片 '{video_id}' 時發生無法恢復的錯誤。\n詳細原因: {exc}"
        )
        return title, None, error_message

    transcript_text = " ".join(entry.get("text", "") for entry in transcript_entries).strip()
    if not transcript_text:
        return title, None, "取得官方字幕失敗：字幕內容為空。"

    return title, transcript_text, None


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
    
    title, transcript, message = get_youtube_content(video_id)

    if message:
        print(f"\n{message}")

    if not transcript:
        if title is None:
            return

        if not WHISPER_AVAILABLE:
            print("Whisper 函式庫未安裝，無法執行 Plan B。")
            return

        print("正在啟動語音轉文字備用方案 (Plan B)...")
        transcript, whisper_error = generate_transcript_with_whisper(video_id)
        if whisper_error:
            print(f"Plan B 失敗：{whisper_error}")
            return

    if not transcript:
        print("\n處理失敗：無法取得影片逐字稿。")
        return

    if title is None:
        title = _fetch_video_title(video_id)

    summary = get_summary_from_gemini(transcript, GEMINI_API_KEY)

    print("\n==================================================")
    print(f"影片標題： {title}")
    print("==================================================")
    print("\n--- AI 重點摘要 ---\n")
    print(summary)
    print("\n-------------------\n")
    # 如果需要，可以取消下一行的註解來顯示完整逐字稿
    # print(f"\n--- 完整逐字稿 ---\n\n{transcript}")
    print("==================================================")

if __name__ == "__main__":
    main()
