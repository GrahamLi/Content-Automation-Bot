from pathlib import Path
import sys

from youtube_transcript_api import NoTranscriptFound, TranscriptsDisabled, VideoUnavailable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import module.summarize_video as summarize_video


class DummyYouTube:
    def __init__(self, *_args, **_kwargs):
        self.title = "Dummy Title"


def setup_youtube_mock(monkeypatch):
    monkeypatch.setattr(summarize_video, "YouTube", DummyYouTube)


def setup_transcript_api_mock(monkeypatch, *, fetch_impl, list_impl=None):
    class FakeYouTubeTranscriptApi:
        def __init__(self, *_args, **_kwargs):
            self._fetch_impl = fetch_impl
            self._list_impl = list_impl

        def fetch(self, video_id, languages):
            if self._fetch_impl is None:
                raise AssertionError("fetch should not be called")
            return self._fetch_impl(video_id, languages)

        def list(self, video_id):
            if self._list_impl is None:
                raise AssertionError("list should not be called")
            return self._list_impl(video_id)

    monkeypatch.setattr(summarize_video, "YouTubeTranscriptApi", FakeYouTubeTranscriptApi)


def test_get_youtube_content_transcripts_disabled_returns_message(monkeypatch):
    setup_youtube_mock(monkeypatch)

    def fetch_impl(_video_id, _languages):
        raise TranscriptsDisabled("disabled")

    setup_transcript_api_mock(monkeypatch, fetch_impl=fetch_impl)

    title, transcript, message = summarize_video.get_youtube_content("video123")

    assert title == "Dummy Title"
    assert transcript is None
    assert message == "這支影片的字幕已被停用，無法取得逐字稿。"


def test_get_youtube_content_video_unavailable_returns_message(monkeypatch):
    setup_youtube_mock(monkeypatch)

    def fetch_impl(_video_id, _languages):
        raise VideoUnavailable("gone")

    setup_transcript_api_mock(monkeypatch, fetch_impl=fetch_impl)

    title, transcript, message = summarize_video.get_youtube_content("video456")

    assert title is None
    assert transcript is None
    assert message == "影片不存在或已移除，無法取得逐字稿。"


def test_get_youtube_content_no_transcript_returns_available_language_message(monkeypatch):
    setup_youtube_mock(monkeypatch)

    def fetch_impl(video_id, _languages):
        raise NoTranscriptFound(video_id, ["zh-Hant"], [])

    class FakeTranscript:
        def __init__(self, language_code, is_translatable):
            self.language_code = language_code
            self.language = language_code
            self.is_translatable = is_translatable

        def translate(self, _target_language):
            raise NoTranscriptFound("video789", ["zh-Hant"], [])

    class FakeTranscriptList:
        def __init__(self, transcripts):
            self._transcripts = transcripts

        def find_transcript(self, _languages):
            raise NoTranscriptFound("video789", ["zh-Hant"], [])

        def __iter__(self):
            return iter(self._transcripts)

    transcripts = [
        FakeTranscript("en", is_translatable=True),
        FakeTranscript("ja", is_translatable=False),
    ]

    setup_transcript_api_mock(
        monkeypatch,
        fetch_impl=fetch_impl,
        list_impl=lambda _video_id: FakeTranscriptList(transcripts),
    )

    title, transcript, message = summarize_video.get_youtube_content("video789")

    assert title == "Dummy Title"
    assert transcript is None
    assert (
        message
        == "影片僅提供以下語言的字幕，且無法翻譯成繁體中文： en, ja。"
    )
