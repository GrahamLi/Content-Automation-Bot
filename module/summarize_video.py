import os
import argparse
import re
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

def get_youtube_content(video_id, target_language="zh-Hant"):
    """根據 video_id 取得影片標題和逐字稿。

    Args:
        video_id: YouTube 影片 ID。
        target_language: 希望取得或翻譯的字幕語系，預設為繁體中文。

    Returns:
        tuple[str | None, str | None, str | None]:
            - title: 影片標題（若取得失敗則為 None）。
            - transcript: 取得成功的字幕內容，失敗時為 None。
            - error_message: 取得字幕失敗時給使用者的說明訊息，成功時為 None。
    """

    try:
        yt = YouTube(f"https://www.youtube.com/watch?v={video_id}")
        title = yt.title
    except Exception as exc:  # pragma: no cover - 極少觸發，仍提供說明
        return None, None, f"無法載入影片資訊：{exc}"

    transcript_api = YouTubeTranscriptApi()
    language_preferences = [target_language, "zh-TW", "zh-Hant", "en", "zh-Hans"]

    try:
        transcript_list = _fetch_transcript(transcript_api, video_id, language_preferences)
        transcript = " ".join(item["text"] for item in transcript_list)
        return title, transcript, None
    except NoTranscriptFound:
        return _handle_missing_transcript(transcript_api, video_id, title, target_language)
    except TranscriptsDisabled:
        message = "這支影片的字幕已被停用，無法取得逐字稿。"
        return title, None, message
    except VideoUnavailable:
        message = "影片不存在或已移除，無法取得逐字稿。"
        return None, None, message
    except Exception as exc:  # pragma: no cover - 捕捉其他罕見錯誤
        message = f"取得字幕時發生未知錯誤：{exc}"
        return title, None, message


def _handle_missing_transcript(transcript_api, video_id, title, target_language):
    """當指定語言字幕不存在時嘗試翻譯其他字幕。"""

    try:
        transcripts_obj = _list_available_transcripts(transcript_api, video_id)
    except TranscriptsDisabled:
        message = "這支影片的字幕已被停用，無法取得逐字稿。"
        return title, None, message
    except VideoUnavailable:
        message = "影片不存在或已移除，無法取得逐字稿。"
        return None, None, message
    except Exception as exc:  # pragma: no cover - 捕捉其他罕見錯誤
        message = f"無法取得字幕清單：{exc}"
        return title, None, message

    transcript_list = None

    try:
        transcript_obj = transcripts_obj.find_transcript([target_language])
        transcript_list = _to_raw_transcript(transcript_obj.fetch())
    except NoTranscriptFound:
        transcript_list = None

    if transcript_list is None:
        available_transcripts = list(transcripts_obj)
        for transcript in available_transcripts:
            if not getattr(transcript, "is_translatable", False):
                continue
            try:
                translated = transcript.translate(target_language)
                transcript_list = _to_raw_transcript(translated.fetch())
                break
            except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable):
                continue
            except Exception:  # pragma: no cover - 忽略其他翻譯錯誤
                continue
    else:
        available_transcripts = list(transcripts_obj)

    if transcript_list:
        transcript = " ".join(item["text"] for item in transcript_list)
        return title, transcript, None

    available_languages = sorted(
        {getattr(t, "language_code", "") for t in available_transcripts if getattr(t, "language_code", "")}
    )

    if available_languages:
        message = (
            "影片僅提供以下語言的字幕，且無法翻譯成"
            f"{_format_target_language(target_language)}： {', '.join(available_languages)}。"
        )
    else:
        message = (
            "這支影片沒有可用的字幕，也無法翻譯成"
            f"{_format_target_language(target_language)}。"
        )

    return title, None, message


def _fetch_transcript(transcript_api, video_id, languages):
    """取得指定語言優先序的字幕內容。"""

    if hasattr(transcript_api, "get_transcript"):
        return transcript_api.get_transcript(video_id, languages=languages)

    if hasattr(YouTubeTranscriptApi, "get_transcript"):
        return YouTubeTranscriptApi.get_transcript(video_id, languages=languages)

    fetched = transcript_api.fetch(video_id, languages=languages)
    return _to_raw_transcript(fetched)


def _list_available_transcripts(transcript_api, video_id):
    """取得可用字幕的 TranscriptList 物件。"""

    if hasattr(transcript_api, "list_transcripts"):
        return transcript_api.list_transcripts(video_id)

    if hasattr(YouTubeTranscriptApi, "list_transcripts"):
        return YouTubeTranscriptApi.list_transcripts(video_id)

    return transcript_api.list(video_id)


def _to_raw_transcript(fetched_transcript):
    """將 FetchedTranscript 轉換成原始資料格式。"""

    if hasattr(fetched_transcript, "to_raw_data"):
        return fetched_transcript.to_raw_data()

    return list(fetched_transcript)


def _format_target_language(target_language):
    """回傳顯示用的目標字幕語言描述。"""

    if target_language == "zh-Hant":
        return "繁體中文"

    return f"指定的語言 ({target_language})"

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
