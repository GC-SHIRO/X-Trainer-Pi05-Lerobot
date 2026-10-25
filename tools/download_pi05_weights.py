"""Download a complete LeRobot Pi05 base and its tokenizer for local training."""
import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKENIZER_FILES = ["config.json", "tokenizer*", "special_tokens_map.json",
                   "added_tokens.json", "*.model", "vocab.json", "merges.txt"]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("hf", "modelscope"), default="hf")
    parser.add_argument("--repo-id", "--model-id", dest="repo_id", default="lerobot/pi05_base")
    parser.add_argument("--tokenizer-repo-id", "--tokenizer-model-id", dest="tokenizer_repo_id")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "models/pi05-base")
    parser.add_argument("--revision")
    parser.add_argument("--tokenizer-revision")
    parser.add_argument("--endpoint", default=os.environ.get("HF_ENDPOINT", "https://huggingface.co"))
    parser.add_argument("--dry-run", action="store_true", help="Print download plan; do not connect or write")
    return parser.parse_args(argv)


def validate_checkpoint(output):
    required = ("config.json", "model.safetensors", "policy_preprocessor.json", "policy_postprocessor.json")
    missing = [name for name in required if not (output / name).is_file() or (output / name).stat().st_size == 0]
    if missing:
        raise ValueError(f"Incomplete Pi05 base: {missing}")
    config = json.loads((output / "config.json").read_text(encoding="utf-8"))
    if config.get("type") != "pi05":
        raise ValueError(f"Expected type=pi05, got {config.get('type')!r}")
    preprocessor = json.loads((output / "policy_preprocessor.json").read_text(encoding="utf-8"))
    json.loads((output / "policy_postprocessor.json").read_text(encoding="utf-8"))
    if not any(step.get("registry_name") == "tokenizer_processor" for step in preprocessor.get("steps", [])):
        raise ValueError("No tokenizer_processor found in base checkpoint")
    return config, preprocessor


def download(args):
    output = args.output_dir.expanduser().resolve()
    tokenizer = output / "tokenizer"
    tokenizer_id = args.tokenizer_repo_id or (
        "google/paligemma-3b-pt-224" if args.source == "hf" else "AI-ModelScope/paligemma-3b-pt-224")
    plan = {"source": args.source, "model": args.repo_id, "revision": args.revision,
            "tokenizer": tokenizer_id, "tokenizer_revision": args.tokenizer_revision,
            "output_dir": str(output), "endpoint": args.endpoint if args.source == "hf" else None}
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    if args.dry_run:
        return
    if args.source == "hf":
        from huggingface_hub import snapshot_download
        def fetch(repo_id, directory, revision, patterns=None):
            return snapshot_download(repo_id=repo_id, revision=revision, local_dir=str(directory),
                                     endpoint=args.endpoint, token=os.environ.get("HF_TOKEN"),
                                     allow_patterns=patterns)
    else:
        from modelscope import snapshot_download
        if os.environ.get("MODELSCOPE_API_TOKEN"):
            from modelscope.hub.api import HubApi
            HubApi().login(os.environ["MODELSCOPE_API_TOKEN"])
        def fetch(repo_id, directory, revision, patterns=None):
            return snapshot_download(model_id=repo_id, revision=revision, local_dir=str(directory),
                                     allow_patterns=patterns)
    fetch(args.repo_id, output, args.revision)
    config, preprocessor = validate_checkpoint(output)
    fetch(tokenizer_id, tokenizer, args.tokenizer_revision, TOKENIZER_FILES)
    from transformers import AutoTokenizer
    AutoTokenizer.from_pretrained(tokenizer, local_files_only=True)
    # Keep provenance and patch only local copies; tokenizer paths survive cwd changes.
    config["text_tokenizer_name"] = str(tokenizer)
    for step in preprocessor["steps"]:
        if step.get("registry_name") == "tokenizer_processor":
            step.setdefault("config", {})["tokenizer_name"] = str(tokenizer)
    for filename, value in (("config.json", config), ("policy_preprocessor.json", preprocessor),
                            ("xtrainer_download.json", plan)):
        (output / filename).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Validated Pi05 base and offline tokenizer: {output}")
    print("Use this base for fine-tuning; serve the resulting X-Trainer checkpoint.")


if __name__ == "__main__":
    download(parse_args())
