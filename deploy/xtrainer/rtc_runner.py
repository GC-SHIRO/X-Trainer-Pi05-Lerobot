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
    previous_send_started = None

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
                logger.info("RTC result: elapsed_steps=%d executed_steps=%d alignment_steps=%d next_delay=%d", elapsed, consumed, consumed, delay)
                if elapsed >= len(incoming):
                    raise RuntimeError("RTC prediction expired; stopping")
                joints = np.r_[0:6, 7:13]
                seam_delta = None if last_sent is None else float(np.max(np.abs(incoming[consumed, joints] - last_sent[joints])))
                revision_delta = float(np.max(np.abs(incoming[consumed, joints] - actions[index, joints]))) if index < len(actions) else None
                logger.info("RTC seam: target_step_delta_rad=%s revised_next_target_delta_rad=%s", seam_delta, revision_delta)
                if log is not None:
                    log.write("rtc_switch", executed_steps=consumed, elapsed_steps=elapsed,
                              target_step_delta_rad=seam_delta, revised_next_target_delta_rad=revision_delta)
                # This executor advances one action per successful apply_action,
                # including when a tick overruns. The prefix is indexed by those
                # actions, not wall-clock slots. Time-based slicing skips targets.
                actions, model, index = incoming[consumed:], incoming_model[consumed:], 0
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
                observation_ms = (clock() - request_started) * 1000
                logger.info("RTC observation acquisition %.1f ms", observation_ms)
                request_step = step
                pending = asyncio.create_task(request(observation, model[index:].copy()))
            action = actions[index].copy()
            if gripper_fn is not None:
                previous = last_sent if last_sent is not None else np.asarray(observation[state_key])
                action = gripper_fn(action, previous)
            action = rate_limit_fn(action, last_sent, max_delta)
            send_started = clock()
            interval_ms = None if previous_send_started is None else (send_started - previous_send_started) * 1000
            previous_send_started = send_started
            joint_indices = np.r_[0:6, 7:13]
            joint_delta = None if last_sent is None else float(np.max(np.abs(action[joint_indices] - last_sent[joint_indices])))
            last_sent = np.asarray(environment.apply_action(action, pace=False), dtype=np.float64)
            apply_ms = (clock() - send_started) * 1000
            if interval_ms is not None and interval_ms > period * 1500:
                logger.warning("Control gap: interval=%.1f ms target=%.1f ms apply=%.1f ms joint_target_delta=%.5f rad",
                               interval_ms, period * 1000, apply_ms, joint_delta)
            if log is not None:
                log.write("control_step", control_timestep=step, rtc=rtc,
                          queued_action=actions[index].tolist(), applied_action=last_sent.tolist(),
                          send_started_monotonic=send_started, send_interval_ms=interval_ms,
                          apply_action_ms=apply_ms, joint_target_delta_rad=joint_delta,
                          action_stages_ms=dict(getattr(environment, "last_action_timing_ms", {})))
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
