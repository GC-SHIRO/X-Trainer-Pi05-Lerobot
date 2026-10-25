"""Serve a fine-tuned Pi05 checkpoint on the X-Trainer transport."""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from deploy.xtrainer.pi05_policy import PI05XTrainerPolicy
from deploy.xtrainer.websocket_policy_server import XTrainerWebSocketPolicyServer


async def serve(args):
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    policy, network = config["policy"], config["network"]
    if policy["type"] != "pi05":
        raise ValueError("policy.type must be pi05")
    checkpoint = Path(args.checkpoint or policy["checkpoint"])
    if not checkpoint.is_absolute():
        checkpoint = ROOT / checkpoint
    count = args.actions_per_chunk if args.actions_per_chunk is not None else policy["actions_per_chunk"]
    adapter = PI05XTrainerPolicy(checkpoint, args.device or policy["device"], count)
    server = XTrainerWebSocketPolicyServer(
        adapter, host=args.host or network["host"],
        port=args.port if args.port is not None else network["port"],
        max_payload_bytes=int(network["max_payload_mb"]) * 1024 * 1024,
    )
    await server.start()
    logging.info("Pi05 server ready on %s:%d", server.host, server.port)
    try:
        await asyncio.Event().wait()
    finally:
        await server.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(ROOT / "configs/xtrainer/deploy.yaml"))
    parser.add_argument("--checkpoint", "--model-path")
    parser.add_argument("--device")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--actions-per-chunk", type=int)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
