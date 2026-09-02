"""Tests for the provider clients. No test here opens a socket or needs a credential."""

from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from ceqa_preflight.ai.client import (
    DEFAULT_MODELS,
    MODEL_ENV,
    PROVIDER_ENV,
    AnthropicClient,
    BedrockClient,
    ModelError,
    ScriptedClient,
    build_client,
    resolve_provider_and_model,
)


class _Block:
    def __init__(self, kind: str, text: str = "") -> None:
        self.type = kind
        self.text = text


class _Usage:
    input_tokens = 12
    output_tokens = 3


class _Message:
    def __init__(self, *, stop_reason: str = "end_turn", model: str = "m") -> None:
        self.content = [_Block("thinking"), _Block("text", '{"a":'), _Block("text", " 1}")]
        self.stop_reason = stop_reason
        self.model = model
        self.usage = _Usage()


class _Messages:
    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class _Sdk:
    def __init__(self, outcome: Any) -> None:
        self.messages = _Messages(outcome)


def test_sdk_client_joins_text_blocks_and_records_usage() -> None:
    sdk = _Sdk(_Message(model="claude-x"))
    client = AnthropicClient("claude-sonnet-5", sdk_client=sdk)

    response = client.complete(system="s", user="u", max_tokens=10)

    assert response.text == '{"a": 1}'
    assert response.model == "claude-x"
    assert response.input_tokens == 12 and response.output_tokens == 3
    assert sdk.messages.calls[0]["model"] == "claude-sonnet-5"
    assert sdk.messages.calls[0]["messages"] == [{"role": "user", "content": "u"}]
    assert client.provider == "anthropic" and client.model == "claude-sonnet-5"


def test_refusal_and_sdk_errors_fail_closed() -> None:
    with pytest.raises(ModelError, match="declined"):
        AnthropicClient("m", sdk_client=_Sdk(_Message(stop_reason="refusal"))).complete(
            system="s", user="u", max_tokens=1
        )
    with pytest.raises(ModelError, match="model call failed \\(RuntimeError\\)"):
        AnthropicClient("m", sdk_client=_Sdk(RuntimeError("429"))).complete(
            system="s", user="u", max_tokens=1
        )
    with pytest.raises(ModelError, match="missing a dependency"):
        BedrockClient("m", sdk_client=_Sdk(ImportError("botocore"))).complete(
            system="s", user="u", max_tokens=1
        )


def test_message_without_usage_or_model_is_tolerated() -> None:
    message = types.SimpleNamespace(content=[_Block("text", "ok")], stop_reason=None, model="")
    response = AnthropicClient("m", sdk_client=_Sdk(message)).complete(
        system="s", user="u", max_tokens=1
    )
    assert response.text == "ok" and response.model == "unknown"
    assert response.input_tokens is None


def test_scripted_client_replays_and_then_fails_closed() -> None:
    client = ScriptedClient(["one"])
    assert client.complete(system="s", user="u", max_tokens=5).text == "one"
    assert client.calls == [{"system": "s", "user": "u", "max_tokens": 5}]
    with pytest.raises(ModelError, match="no response left"):
        client.complete(system="s", user="u", max_tokens=5)


def test_provider_resolution_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PROVIDER_ENV, raising=False)
    monkeypatch.delenv(MODEL_ENV, raising=False)
    assert resolve_provider_and_model() == ("anthropic", DEFAULT_MODELS["anthropic"])
    monkeypatch.setenv(PROVIDER_ENV, "bedrock")
    monkeypatch.setenv(MODEL_ENV, "custom")
    assert resolve_provider_and_model() == ("bedrock", "custom")
    assert resolve_provider_and_model("Anthropic", "m2") == ("anthropic", "m2")
    with pytest.raises(ModelError, match="unsupported provider"):
        resolve_provider_and_model("openai")


def test_build_client_imports_the_sdk_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[dict[str, Any]] = []
    fake = types.ModuleType("anthropic")

    class Anthropic:
        def __init__(self, **kwargs: Any) -> None:
            created.append({"kind": "anthropic", **kwargs})

    class AnthropicBedrock:
        def __init__(self, **kwargs: Any) -> None:
            created.append({"kind": "bedrock", **kwargs})

    fake.Anthropic = Anthropic  # type: ignore[attr-defined]
    fake.AnthropicBedrock = AnthropicBedrock  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    monkeypatch.delenv(PROVIDER_ENV, raising=False)
    monkeypatch.delenv(MODEL_ENV, raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)

    with pytest.raises(ModelError, match="ANTHROPIC_API_KEY is not set"):
        build_client()
    with pytest.raises(ModelError, match="AWS_REGION is not set"):
        build_client("bedrock")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key-for-tests")
    client = build_client()
    assert client.provider == "anthropic" and created[-1] == {"kind": "anthropic"}
    bedrock = build_client("bedrock", region="us-west-2")
    assert bedrock.provider == "bedrock"
    assert created[-1] == {"kind": "bedrock", "aws_region": "us-west-2"}


def test_missing_sdk_is_a_model_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "anthropic", None)  # makes `import anthropic` fail
    with pytest.raises(ModelError, match="not installed"):
        AnthropicClient("m")
    with pytest.raises(ModelError, match="not installed"):
        BedrockClient("m")


def test_default_cli_path_never_imports_the_provider_sdk() -> None:
    """Importing the CLI and loading the catalog must not import `anthropic` (ADR 0002)."""

    code = (
        "import sys; import ceqa_preflight.cli; from ceqa_preflight.rule_registry import "
        "default_catalog; default_catalog(); "
        "assert 'anthropic' not in sys.modules, 'anthropic was imported on the default path'"
    )
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr


def test_the_bedrock_default_is_a_model_this_project_has_actually_invoked() -> None:
    """The two provider defaults differ on purpose; this pins the reason.

    `anthropic.claude-sonnet-5` returns HTTP 403 on Bedrock for the account every recorded
    run in `evals/` was produced on, including on a probe taken after the entitlement API
    reported it AUTHORIZED. A Bedrock default of Sonnet 5 therefore makes `ceqa-preflight
    ai` unusable out of the box on the only provider this project has live evidence for,
    while every result file under `evals/*/results/` names Sonnet 4.6.

    The Anthropic API default stays `claude-sonnet-5`, which is ADR 0002's settled choice
    and what a deployer with an ordinary API key gets. Asserted here so that "make the two
    defaults match" is a change someone has to argue for rather than tidy up.
    """

    assert DEFAULT_MODELS["anthropic"] == "claude-sonnet-5"
    assert DEFAULT_MODELS["bedrock"] == "global.anthropic.claude-sonnet-4-6"

    results = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (Path(__file__).resolve().parent.parent / "evals").glob("*/results/*.json")
    ]
    # A suite that did not run records `provenance: null` and a `reason_not_run`, which is
    # not evidence of anything having been invoked.
    recorded = {
        result["provenance"]["model"] for result in results if result.get("provenance") is not None
    }
    assert recorded, "no recorded live eval run; this check would be vacuous"
    assert DEFAULT_MODELS["bedrock"] in recorded, (
        f"the Bedrock default {DEFAULT_MODELS['bedrock']!r} has no recorded live run; "
        f"the suites in evals/ were run on {sorted(recorded)}"
    )
