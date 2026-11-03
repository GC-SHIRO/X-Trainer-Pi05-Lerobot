"""Sequential or guided RTC execution, with one outstanding prediction."""
import asyncio
import logging
import numpy as np


async def execute_chunks(policy, environment, *, payload_fn, extract_fn, rate_limit_fn,
                         gripper_fn, state_key, action_horizon, control_hz, max_steps,
                         timeout, max_delta, log, clock, sleep):
    metadata = (getattr(policy, "metadata", None) or {}).get("policy", {})
    rtc = bool(metadata.get("rtc_enabled"))
    horizon = int(metadata["chunk_size"]) if rtc else action_horizon
    logger = logging.getLogger(__name__)
    logger.info("Execution mode=%s prediction_steps=%d control_hz=%.2f", "guided RTC" if rtc else "sequential", horizon, control_hz)
    period = 1 / control_hz
    pending = None
    last_sent = None
    delay = 1
    step = 0

    async def request(observation, prefix=None):
        payload = payload_fn(observation)
        if rtc:
            payload.update(prev_chunk_left_over=prefix,
                           inference_delay=delay if prefix is not None else 0)
        return await asyncio.wait_for(policy.infer(payload), timeout)

    def unpack(response):
        actions = extract_fn(response, horizon)
        model = None
        if rtc:
            model = np.asarray(response.get("model_action"), dtype=np.float32)
            if model.shape != actions.shape or not np.isfinite(model).all():
                raise ValueError("Invalid RTC model-space actions")
        return actions, model

    try:
        started = clock()
        observation = environment.get_observation()
        actions, model = unpack(await request(observation))
        delay = max(1, int(np.ceil((clock() - started) / period)) + 2)
        index = 0
        deadline = clock()
        while step < max_steps:
            if pending is not None and pending.done():
                response = pending.result()
                pending = None
                incoming, incoming_model = unpack(response)
                consumed = step - request_step
                elapsed = max(consumed, int(np.ceil((clock() - request_started) / period)))
                delay = max(1, elapsed + 2)
                logger.info("RTC result: elapsed_steps=%d executed_steps=%d next_delay=%d", elapsed, consumed, delay)
                if elapsed >= len(incoming):
                    raise RuntimeError("RTC prediction expired; stopping")
                actions, model, index = incoming[elapsed:], incoming_model[elapsed:], 0
            remaining = len(actions) - index
            if remaining == 0:
                if rtc:
                    raise RuntimeError("RTC queue exhausted; stopping")
                observation = environment.get_observation()
                last_sent = np.asarray(environment.apply_action(observation[state_key], pace=False))
                actions, model = unpack(await request(observation))
                index = 0
                deadline = clock()
                remaining = len(actions)
            if rtc and pending is None and remaining <= max(15, delay + 5):
                if remaining <= delay:
                    raise RuntimeError("RTC prefix cannot cover observed latency")
                request_started = clock()
                observation = environment.get_observation()
                request_step = step
                pending = asyncio.create_task(request(observation, model[index:].copy()))
            action = actions[index].copy()
            if gripper_fn is not None:
                previous = last_sent if last_sent is not None else np.asarray(observation[state_key])
                action = gripper_fn(action, previous)
            action = rate_limit_fn(action, last_sent, max_delta)
            last_sent = np.asarray(environment.apply_action(action, pace=False), dtype=np.float64)
            if log is not None:
                log.write("control_step", control_timestep=step, rtc=rtc,
                          queued_action=actions[index].tolist(), applied_action=last_sent.tolist())
            index += 1
            step += 1
            deadline = max(deadline + period, clock())
            await sleep(max(0, deadline - clock()))
    finally:
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        if last_sent is not None:
            observation = environment.get_observation()
            environment.apply_action(observation[state_key], pace=False)
