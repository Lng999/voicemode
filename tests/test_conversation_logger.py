"""Tests for ConversationLogger's view of the last exchange-log entry.

The logger reads the last line of today's exchanges file to decide whether to
continue a conversation (restart within the gap) or start a new one (gap
exceeded). That line is often longer than 1 KB: a TTS entry carries the whole
spoken message plus metadata.
"""

import json
from datetime import datetime, timedelta

import pytest

from voice_mode.conversation_logger import ConversationLogger


LONG_MESSAGE = "This reply is long enough to push its log line past one block. " * 80


def _age_last_entry(logger: ConversationLogger, minutes: int) -> None:
    """Rewrite today's last entry as if it was written `minutes` ago."""
    log_file = logger._get_log_file_path(datetime.now().date())
    lines = log_file.read_text().splitlines()
    entry = json.loads(lines[-1])
    entry["timestamp"] = (
        datetime.now().astimezone() - timedelta(minutes=minutes)
    ).isoformat()
    lines[-1] = json.dumps(entry)
    log_file.write_text("\n".join(lines) + "\n")


@pytest.mark.parametrize("text", ["short reply", LONG_MESSAGE])
def test_last_entry_is_read_whatever_its_length(tmp_path, text):
    logger = ConversationLogger(base_dir=tmp_path)
    logger.log_stt("an earlier line")
    logger.log_tts(text, voice="af_sky")

    log_file = logger._get_log_file_path(datetime.now().date())
    if text == LONG_MESSAGE:
        assert len(log_file.read_bytes().splitlines()[-1]) > 4096

    entry = logger._read_last_line(log_file)
    assert entry is not None
    assert entry["text"] == text
    assert entry["conversation_id"] == logger.conversation_id


@pytest.mark.parametrize("text", ["short reply", LONG_MESSAGE])
def test_gap_after_a_long_entry_starts_a_new_conversation(tmp_path, text):
    logger = ConversationLogger(base_dir=tmp_path)
    logger.log_tts(text, voice="af_sky")
    first_id = logger.conversation_id

    _age_last_entry(logger, minutes=ConversationLogger.CONVERSATION_GAP_MINUTES + 5)
    logger.log_stt("back after a break")

    assert logger.conversation_id != first_id


def test_restart_continues_the_conversation_after_a_long_entry(tmp_path):
    first = ConversationLogger(base_dir=tmp_path)
    first.log_tts(LONG_MESSAGE, voice="af_sky")

    second = ConversationLogger(base_dir=tmp_path)

    assert second.conversation_id == first.conversation_id


def test_last_line_is_found_when_the_file_is_one_long_line(tmp_path):
    logger = ConversationLogger(base_dir=tmp_path)
    logger.log_tts(LONG_MESSAGE * 5, voice="af_sky")

    log_file = logger._get_log_file_path(datetime.now().date())
    assert log_file.read_bytes().count(b"\n") == 1

    entry = logger._read_last_line(log_file)
    assert entry is not None and entry["text"] == LONG_MESSAGE * 5
