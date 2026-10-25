"""Exercise download planning and local tokenizer wiring without network access."""
import json
import sys
from types import ModuleType

import pytest

from tools.download_pi05_weights import download, parse_args, validate_checkpoint


def test_download_dry_run_creates_nothing(tmp_path):
    output = tmp_path / "base"
    download(parse_args(["--output-dir", str(output), "--dry-run"]))
    assert not output.exists()


def test_reject_wrong_checkpoint(tmp_path):
    for name, content in {
        "config.json": '{"type":"xvla"}',
        "model.safetensors": "weights",
        "policy_preprocessor.json": '{"steps":[]}',
        "policy_postprocessor.json": "{}",
    }.items():
        (tmp_path / name).write_text(content)
    with pytest.raises(ValueError, match="Expected type=pi05"):
        validate_checkpoint(tmp_path)


@pytest.mark.parametrize("source", ["hf", "modelscope"])
def test_download_wires_offline_tokenizer(tmp_path, monkeypatch, source):
    output = tmp_path / "base"
    calls = []
    def fetch(**kwargs):
        calls.append(kwargs)
        directory = __import__("pathlib").Path(kwargs["local_dir"])
        directory.mkdir(parents=True, exist_ok=True)
        if directory.name == "tokenizer":
            (directory / "tokenizer.json").write_text("{}")
        else:
            (directory / "config.json").write_text('{"type":"pi05"}')
            (directory / "model.safetensors").write_text("test weights")
            (directory / "policy_preprocessor.json").write_text(json.dumps(
                {"steps": [{"registry_name": "tokenizer_processor", "config": {"tokenizer_name": "remote"}}]}))
            (directory / "policy_postprocessor.json").write_text("{}")
    provider = ModuleType("huggingface_hub" if source == "hf" else "modelscope")
    provider.snapshot_download = fetch
    monkeypatch.setitem(sys.modules, provider.__name__, provider)
    monkeypatch.delenv("MODELSCOPE_API_TOKEN", raising=False)
    transformers = ModuleType("transformers")
    loaded = []
    class Tokenizer:
        @staticmethod
        def from_pretrained(path, **kwargs):
            loaded.append((path, kwargs))
    transformers.AutoTokenizer = Tokenizer
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    download(parse_args(["--source", source, "--output-dir", str(output),
                         "--revision", "model-version", "--tokenizer-revision", "tokenizer-version"]))
    assert calls[0]["revision"] == "model-version" and calls[0]["allow_patterns"] is None
    assert calls[1]["revision"] == "tokenizer-version" and "*.model" in calls[1]["allow_patterns"]
    assert loaded[0][1] == {"local_files_only": True}
    config = json.loads((output / "config.json").read_text())
    pre = json.loads((output / "policy_preprocessor.json").read_text())
    assert config["text_tokenizer_name"] == str((output / "tokenizer").resolve())
    assert pre["steps"][0]["config"]["tokenizer_name"] == config["text_tokenizer_name"]
    assert (output / "xtrainer_download.json").is_file()
