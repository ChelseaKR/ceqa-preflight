"""Model provider clients for the opt-in AI layer.

The provider SDK is imported only when a client is built, so the default ``check`` path
never imports it and never needs it installed. Credentials come from the environment
alone (``ANTHROPIC_API_KEY`` for the Anthropic API; the AWS credential chain for Bedrock);
nothing here reads, writes, or prints a key. Every client returns plain text; the callers
parse it strictly and treat it as untrusted.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any, Protocol

from pydantic import Field

from ceqa_preflight.models import StrictModel

PROVIDER_ENV = "CEQA_PREFLIGHT_AI_PROVIDER"
MODEL_ENV = "CEQA_PREFLIGHT_AI_MODEL"
DEFAULT_PROVIDER = "anthropic"
DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5",
    "bedrock": "global.anthropic.claude-sonnet-5",
}
SUPPORTED_PROVIDERS = tuple(DEFAULT_MODELS)


class ModelError(RuntimeError):
    """Raised when a model call cannot complete; callers fail closed on it."""


class ModelResponse(StrictModel):
    """The text a model returned, with enough metadata to record provenance."""

    text: str
    model: str = Field(min_length=1)
    stop_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class ModelClient(Protocol):
    """What the AI layer needs from a provider: one completion at a time."""

    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    def complete(self, *, system: str, user: str, max_tokens: int) -> ModelResponse: ...


def _text_of(message: Any) -> str:
    return "".join(
        str(getattr(block, "text", ""))
        for block in getattr(message, "content", [])
        if getattr(block, "type", None) == "text"
    )


def _response_from(message: Any) -> ModelResponse:
    stop_reason = getattr(message, "stop_reason", None)
    if stop_reason == "refusal":
        raise ModelError("the model provider declined this request (stop_reason=refusal)")
    usage = getattr(message, "usage", None)
    return ModelResponse(
        text=_text_of(message),
        model=str(getattr(message, "model", "") or "unknown"),
        stop_reason=None if stop_reason is None else str(stop_reason),
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
    )


class _SdkClient:
    """Shared completion path over an ``anthropic``-style client object."""

    provider = "sdk"

    def __init__(self, model: str, sdk_client: Any) -> None:
        self._model = model
        self._sdk = sdk_client

    @property
    def model(self) -> str:
        return self._model

    def complete(self, *, system: str, user: str, max_tokens: int) -> ModelResponse:
        try:
            message = self._sdk.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except ModelError:
            raise
        except ImportError as error:
            raise ModelError(
                "the provider SDK is missing a dependency; for Bedrock install "
                f"ceqa-preflight[ai-bedrock] ({error})"
            ) from error
        except Exception as error:  # provider SDKs raise several classes across releases
            raise ModelError(f"model call failed ({type(error).__name__}): {error}") from error
        return _response_from(message)


class AnthropicClient(_SdkClient):
    """The Anthropic API through the public ``anthropic`` SDK."""

    provider = "anthropic"

    def __init__(self, model: str, *, sdk_client: Any | None = None) -> None:
        if sdk_client is None:
            try:
                import anthropic
            except ImportError as error:
                raise ModelError(
                    "the anthropic SDK is not installed; install ceqa-preflight[ai]"
                ) from error
            if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
                raise ModelError("ANTHROPIC_API_KEY is not set in the environment")
            sdk_client = anthropic.Anthropic()
        super().__init__(model, sdk_client)


class BedrockClient(_SdkClient):
    """Amazon Bedrock through the same SDK; credentials come from the AWS chain."""

    provider = "bedrock"

    def __init__(
        self, model: str, *, region: str | None = None, sdk_client: Any | None = None
    ) -> None:
        if sdk_client is None:
            try:
                from anthropic import AnthropicBedrock
            except ImportError as error:
                raise ModelError(
                    "the anthropic SDK is not installed; install ceqa-preflight[ai-bedrock]"
                ) from error
            region = region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
            if not region:
                raise ModelError("AWS_REGION is not set in the environment")
            sdk_client = AnthropicBedrock(aws_region=region)
        super().__init__(model, sdk_client)


class ScriptedClient:
    """A client that replays prepared responses; used by tests and eval replays."""

    provider = "scripted"

    def __init__(self, responses: Sequence[str], *, model: str = "scripted-model") -> None:
        self._responses = list(responses)
        self._model = model
        self.calls: list[dict[str, Any]] = []

    @property
    def model(self) -> str:
        return self._model

    def complete(self, *, system: str, user: str, max_tokens: int) -> ModelResponse:
        self.calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        if not self._responses:
            raise ModelError("scripted client has no response left")
        return ModelResponse(text=self._responses.pop(0), model=self._model)


def resolve_provider_and_model(
    provider: str | None = None, model: str | None = None
) -> tuple[str, str]:
    """Apply explicit arguments, then environment, then defaults."""

    chosen_provider = (provider or os.environ.get(PROVIDER_ENV) or DEFAULT_PROVIDER).lower()
    if chosen_provider not in DEFAULT_MODELS:
        raise ModelError(
            f"unsupported provider {chosen_provider!r}; expected one of "
            + ", ".join(SUPPORTED_PROVIDERS)
        )
    chosen_model = model or os.environ.get(MODEL_ENV) or DEFAULT_MODELS[chosen_provider]
    return chosen_provider, chosen_model


def build_client(
    provider: str | None = None, model: str | None = None, *, region: str | None = None
) -> ModelClient:
    """Build the configured client, importing the provider SDK only now."""

    chosen_provider, chosen_model = resolve_provider_and_model(provider, model)
    if chosen_provider == "bedrock":
        return BedrockClient(chosen_model, region=region)
    return AnthropicClient(chosen_model)
