"""RTC prefix alignment under slow observation acquisition."""
import asyncio

import numpy as np
import pytest

# Load the hardware-free runner without importing optional camera dependencies.
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "rtc_runner_under_test", Path(__file__).resolve().parents[2] / "deploy/xtrainer/rtc_runner.py"
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
execute_chunks = _module.execute_chunks


@pytest.mark.parametrize("observation_delay", [0.0, 0.12])
def test_rtc_switch_preserves_action_sequence_when_control_ticks_overrun(observation_delay):
    async def scenario():
        now = [0.0]
        sent = []
        events = []

        class Environment:
            def get_observation(self):
                now[0] += observation_delay
                return {"state": np.zeros(14)}

            def apply_action(self, action, *, pace):
                sent.append(np.asarray(action).copy())
                now[0] += 0.005
                return action

        class Policy:
            metadata = {"policy": {"rtc_enabled": True, "chunk_size": 50}}

            async def infer(self, payload):
                # Allow execution to proceed while this prediction is pending.
                for _ in range(3):
                    await asyncio.sleep(0)
                prefix = payload.get("prev_chunk_left_over")
                start = 0 if prefix is None else int(prefix[0, 0])
                actions = np.repeat(np.arange(start, start + 50)[:, None], 14, axis=1)
                return {"action": actions, "model_action": actions}

        class Log:
            def write(self, event, **fields):
                events.append(fields)

        async def sleep(seconds):
            now[0] += seconds
            await asyncio.sleep(0)

        await execute_chunks(
            Policy(), Environment(), payload_fn=lambda obs: dict(obs),
            extract_fn=lambda result, horizon: result["action"][:horizon],
            rate_limit_fn=lambda action, previous, limit: action,
            gripper_fn=None, state_key="state", action_horizon=50,
            control_hz=30, max_steps=100, timeout=5, max_delta=0,
            log=Log(), clock=lambda: now[0], sleep=sleep,
        )
        # Exclude the final cleanup hold. Predictions reproduce the prefix
        # exactly, so any missing value is a client-side alignment error.
        np.testing.assert_array_equal(np.asarray(sent[:100])[:, 0], np.arange(100))
        assert len(events) == 100
        assert events[0]["send_interval_ms"] is None
        assert all(event["apply_action_ms"] >= 0 for event in events)
        if observation_delay:
            assert max(event["send_interval_ms"] or 0 for event in events) > 100

    asyncio.run(scenario())
