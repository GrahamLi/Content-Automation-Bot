from pathlib import Path
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import module.summarize_video as summarize_video


def test_call_transcript_method_instantiates_owner_for_instance_method():
    class NeedsInstance:
        instances = []

        def __init__(self):
            NeedsInstance.instances.append(self)
            self.calls = []

        def perform(self, payload):
            self.calls.append(payload)
            return f"handled:{payload}"

    NeedsInstance.instances.clear()

    result = summarize_video._call_transcript_method(
        NeedsInstance, "perform", "data"
    )

    assert result == "handled:data"
    assert len(NeedsInstance.instances) == 1
    assert NeedsInstance.instances[0].calls == ["data"]


def test_call_transcript_method_reraises_unrelated_type_error():
    class RaisesTypeError:
        def perform(self, payload):
            raise TypeError("custom failure")

    with pytest.raises(TypeError, match="custom failure"):
        summarize_video._call_transcript_method(RaisesTypeError, "perform", "data")
