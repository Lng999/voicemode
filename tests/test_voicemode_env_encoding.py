"""voicemode.env is read and written as UTF-8 whatever the locale.

Without an explicit encoding, ``open()`` uses the locale's code page on
Windows (cp1251, cp1252, cp932, ...). So a UTF-8 voicemode.env (what Notepad
and VS Code save) was read as mojibake, and on a code page without ``×``
(cp1251, cp1253, cp874) a fresh install could not write the default template:
``import voice_mode.config`` raised UnicodeEncodeError.

The tests force a non-UTF-8 default for ``open()`` so they fail the same way
on any platform.
"""

import builtins
import io
import locale
import os
from unittest.mock import patch

import pytest

from voice_mode import config as vm_config
from voice_mode.config import load_voicemode_env


def _force_default_encoding(monkeypatch, codec):
    """Make text-mode ``open()`` without an encoding use ``codec``, as on Windows."""
    real_open = builtins.open

    def open_with_codec(file, mode="r", buffering=-1, encoding=None, *args, **kwargs):
        # Path.read_text()/write_text() pass encoding="locale" on 3.10+.
        if "b" not in mode and encoding in (None, "locale"):
            encoding = codec
        return real_open(file, mode, buffering, encoding, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", open_with_codec)
    monkeypatch.setattr(io, "open", open_with_codec)


@pytest.fixture
def cp1251_default(monkeypatch):
    """Russian Windows: no '×' in the code page."""
    _force_default_encoding(monkeypatch, "cp1251")


@pytest.fixture
def cp932_default(monkeypatch):
    """Japanese Windows: UTF-8 '×' (C3 97) is not a valid cp932 sequence."""
    _force_default_encoding(monkeypatch, "cp932")


UTF8_ENV = "# 1.7B: ~2× realtime\nVOICEMODE_TEST_UTF8=café\n"


@pytest.fixture
def clean_voicemode_env():
    saved = {k: v for k, v in os.environ.items() if k.startswith("VOICEMODE_")}
    for k in saved:
        del os.environ[k]
    yield
    for k in [k for k in os.environ if k.startswith("VOICEMODE_")]:
        del os.environ[k]
    os.environ.update(saved)


def test_fresh_install_writes_the_template_on_any_code_page(
    tmp_path, cp1251_default, clean_voicemode_env
):
    home = tmp_path / "home"
    with patch.object(vm_config.Path, "home", return_value=home), \
         patch.object(vm_config, "find_voicemode_env_files", return_value=[]):
        load_voicemode_env()

    written = (home / ".voicemode" / "voicemode.env").read_bytes()
    assert "×".encode("utf-8") in written       # the template's non-ASCII, as UTF-8
    written.decode("utf-8")


def test_utf8_file_is_read_as_utf8(tmp_path, cp1251_default, clean_voicemode_env):
    env = tmp_path / "voicemode.env"
    env.write_bytes("VOICEMODE_TEST_UTF8=café → ok\n".encode("utf-8"))

    with patch.object(vm_config, "find_voicemode_env_files", return_value=[env]):
        load_voicemode_env()

    assert os.environ["VOICEMODE_TEST_UTF8"] == "café → ok"


@pytest.mark.skipif(
    locale.getpreferredencoding(False).lower().replace("-", "") == "utf8",
    reason="a locale-encoded file is UTF-8 here; the legacy case cannot occur",
)
def test_file_from_an_older_version_in_the_locale_encoding_still_loads(
    tmp_path, clean_voicemode_env
):
    """Older versions wrote voicemode.env in the locale encoding; keep reading those."""
    enc = locale.getpreferredencoding(False)
    env = tmp_path / "voicemode.env"
    raw = "VOICEMODE_TEST_LEGACY=2×\n".encode(enc)
    try:
        raw.decode("utf-8")
        pytest.skip(f"{enc} encodes this sample as valid UTF-8")
    except UnicodeDecodeError:
        pass
    env.write_bytes(raw)

    with patch.object(vm_config, "find_voicemode_env_files", return_value=[env]):
        load_voicemode_env()
    assert os.environ["VOICEMODE_TEST_LEGACY"] == "2×"


def test_configuration_tools_round_trip_utf8(tmp_path, cp1251_default):
    from voice_mode.tools.configuration_management import parse_env_file, write_env_file

    env = tmp_path / "voicemode.env"
    env.write_bytes("# comment with × in it\nVOICEMODE_VOICES=af_sky\n".encode("utf-8"))

    write_env_file(env, {"VOICEMODE_VOICES": "af_sky", "VOICEMODE_TEST_UTF8": "café"})

    text = env.read_bytes().decode("utf-8")
    assert "# comment with × in it" in text
    assert parse_env_file(env)["VOICEMODE_TEST_UTF8"] == "café"


@pytest.mark.parametrize("module_name, key", [
    ("voice_mode.cli_commands.soundfonts", "VOICEMODE_SOUNDFONTS_ENABLED"),
    ("voice_mode.cli_commands.autofocus", "VOICEMODE_AUTO_FOCUS_PANE"),
])
def test_cli_toggles_rewrite_a_utf8_file_as_utf8(
    tmp_path, monkeypatch, cp932_default, clean_voicemode_env, module_name, key
):
    import importlib
    module = importlib.import_module(module_name)
    env = tmp_path / "voicemode.env"
    env.write_bytes(UTF8_ENV.encode("utf-8"))
    monkeypatch.setattr(module, "VOICEMODE_ENV_FILE", env)

    module._update_env_file(False)

    text = env.read_bytes().decode("utf-8")
    assert "~2× realtime" in text and "VOICEMODE_TEST_UTF8=café" in text
    assert f"{key}=false" in text


def test_whisper_set_active_model_rewrites_a_utf8_file_as_utf8(
    tmp_path, cp932_default, clean_voicemode_env
):
    from voice_mode.tools.whisper import models

    home = tmp_path / "home"
    (home / ".voicemode").mkdir(parents=True, exist_ok=True)
    env = home / ".voicemode" / "voicemode.env"
    env.write_bytes(UTF8_ENV.encode("utf-8"))

    with patch.object(models.Path, "home", return_value=home):
        models.set_active_model("base")

    text = env.read_bytes().decode("utf-8")
    assert "~2× realtime" in text and "VOICEMODE_TEST_UTF8=café" in text
    assert "VOICEMODE_WHISPER_MODEL=base" in text


def test_utf8_file_with_a_bom_is_read_without_it(tmp_path, clean_voicemode_env):
    """Older Notepad saves UTF-8 with a BOM; the first key must still match."""
    env = tmp_path / "voicemode.env"
    env.write_bytes(b"\xef\xbb\xbf" + "VOICEMODE_TEST_BOM=café\n".encode("utf-8"))

    with patch.object(vm_config, "find_voicemode_env_files", return_value=[env]):
        load_voicemode_env()

    assert os.environ.get("VOICEMODE_TEST_BOM") == "café"


def test_config_resource_reads_a_utf8_file(tmp_path, cp932_default):
    from voice_mode.resources.configuration import parse_env_file

    env = tmp_path / "voicemode.env"
    env.write_bytes(UTF8_ENV.encode("utf-8"))

    assert parse_env_file(env).get("VOICEMODE_TEST_UTF8") == "café"
