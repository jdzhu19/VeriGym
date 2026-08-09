"""rLLM Workflow that requests sparse rewards from a host-side VeriGym broker."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from rllm.agents.agent import (  # type: ignore[import-not-found]
    Action,
    Episode,
    Step,
    Trajectory,
)
from rllm.engine import ModelOutput, RolloutEngine  # type: ignore[import-not-found]
from rllm.workflows.workflow import (  # type: ignore[import-not-found]
    TerminationEvent,
    TerminationReason,
    Workflow,
)

from .rtl import extract_rtl_candidate


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


class VeriGymRtlWorkflow(Workflow):  # type: ignore[misc]
    """Two-turn RTL generation followed by evaluator-owned sparse verification."""

    def __init__(
        self,
        rollout_engine: RolloutEngine,
        *,
        verifier_broker_root: str,
        verifier_timeout_s: int = 300,
        plan_tokens: int = 96,
        solution_tokens: int = 512,
        **kwargs: Any,
    ) -> None:
        super().__init__(rollout_engine, **kwargs)
        self.verifier_broker_root = Path(verifier_broker_root).resolve(strict=True)
        self.verifier_timeout_s = verifier_timeout_s
        self.plan_tokens = plan_tokens
        self.solution_tokens = solution_tokens

    def _verify(self, task: dict[str, Any], candidate: str, uid: str) -> dict[str, Any]:
        if len(candidate.encode()) > 1024 * 1024:
            raise RuntimeError("online candidate exceeds the verifier request limit")
        requests = self.verifier_broker_root / "requests"
        responses = self.verifier_broker_root / "responses"
        if not requests.is_dir() or not responses.is_dir():
            raise RuntimeError("online verifier broker is unavailable")
        request_id = hashlib.sha256(f"{uid}:{uuid.uuid4().hex}".encode()).hexdigest()
        base = {
            "schema_version": "1.0",
            "format_id": "verigym_online_verifier_request_v1",
            "request_id": request_id,
            "task_id": task["task_id"],
            "public_input_hash": task["record_hash"],
            "candidate": candidate,
            "candidate_hash": hashlib.sha256(candidate.encode()).hexdigest(),
            "seed": int(task.get("seed", 20260809)),
            "sample_index": int(task.get("sample_index", 0)),
        }
        request = {**base, "request_hash": _canonical_hash(base)}
        _atomic_json(requests / f"{request_id}.json", request)
        response_path = responses / f"{request_id}.json"
        deadline = time.monotonic() + self.verifier_timeout_s
        while not response_path.is_file():
            if time.monotonic() >= deadline:
                raise RuntimeError("online verifier broker timed out")
            time.sleep(0.1)
        response = json.loads(response_path.read_text(encoding="utf-8"))
        identity = dict(response)
        expected_hash = identity.pop("response_hash", None)
        if (
            response.get("format_id") != "verigym_online_verifier_response_v1"
            or response.get("request_id") != request_id
            or response.get("request_hash") != request["request_hash"]
            or not isinstance(expected_hash, str)
            or _canonical_hash(identity) != expected_hash
        ):
            raise RuntimeError("online verifier response identity is invalid")
        if response.get("infrastructure_valid") is not True:
            raise RuntimeError("VeriGym verifier reported an infrastructure-invalid outcome")
        if response.get("resolved") not in {True, False}:
            raise RuntimeError("online verifier response omits a binary task outcome")
        return {
            "resolved": response["resolved"],
            "compile_status": response["compile_status"],
            "task_hash": response["task_hash"],
            "verifier_hash": response["verifier_hash"],
            "candidate_hash": response["candidate_hash"],
            "request_hash": response["request_hash"],
        }

    async def run(self, task: dict[str, Any], uid: str, **kwargs: Any) -> Episode:
        self.reset(task, uid)
        if task.get("hidden_assets_included") is not False:
            raise RuntimeError("online rollout task did not explicitly exclude hidden assets")
        material = (
            f"TASK DESCRIPTION\n{task['task_description']}\n\n"
            f"PUBLIC README\n{task['public_readme']}\n\n"
            f"CURRENT FILE ({task['candidate_path']})\n{task['candidate_skeleton']}"
        )
        system = {
            "role": "system",
            "content": (
                "You are a professional RTL design agent. Use only the supplied public task "
                "material."
            ),
        }
        plan_messages = [
            system,
            {
                "role": "user",
                "content": material
                + "\n\nAnalyze the required behavior and give a concise implementation plan. "
                "Do not emit the final Verilog yet.",
            },
        ]
        plan: ModelOutput = await self.rollout_engine.get_model_response(
            plan_messages,
            application_id=f"{uid}:plan",
            max_tokens=self.plan_tokens,
        )
        plan_text = plan.content or plan.text
        solution_messages = [
            *plan_messages,
            {"role": "assistant", "content": plan_text},
            {
                "role": "user",
                "content": (
                    "Now return the complete candidate source and nothing else between "
                    "<verilog> and </verilog> tags. Preserve the exact requested module interface."
                ),
            },
        ]
        solution: ModelOutput = await self.rollout_engine.get_model_response(
            solution_messages,
            application_id=f"{uid}:solution",
            max_tokens=self.solution_tokens,
        )
        solution_text = solution.content or solution.text
        candidate, extraction = extract_rtl_candidate(solution_text)
        verification = await self.run_in_executor(self._verify, task, candidate, uid)
        reward = float(verification["resolved"])
        trajectory = Trajectory(
            name="verigym_rtl_online_v1",
            task=task["task_id"],
            input={"public_input_hash": task["record_hash"]},
            output=candidate,
            reward=reward,
            steps=[
                Step(
                    chat_completions=[
                        *plan_messages,
                        {"role": "assistant", "content": plan_text},
                    ],
                    action=Action(action=plan_text),
                    reward=0.0,
                    model_output=plan,
                    metadata={"turn": 0, "trainable": True},
                ),
                Step(
                    chat_completions=[
                        *solution_messages,
                        {"role": "assistant", "content": solution_text},
                    ],
                    action=Action(action=candidate),
                    reward=reward,
                    model_output=solution,
                    metadata={
                        "turn": 1,
                        "trainable": True,
                        "candidate_extraction": extraction,
                        "verification": verification,
                    },
                ),
            ],
            metadata={
                "public_input_hash": task["record_hash"],
                "hidden_assets_loaded_by_model": False,
                "reference_solution_loaded_by_model": False,
            },
        )
        self.commit(trajectory=trajectory)
        if solution.finish_reason == "length":
            raise TerminationEvent(TerminationReason.MAX_RESPONSE_LENGTH_EXCEEDED)
        raise TerminationEvent(TerminationReason.ENV_DONE)


__all__ = ["VeriGymRtlWorkflow"]
