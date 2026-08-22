"""Canonical failure model normalising Razorpay's two error wire shapes.

Razorpay reports the same underlying payment failure differently depending
on which surface reports it:

- A ``payment.failed`` **webhook** nests the error under
  ``payload.payment.entity`` using the keys ``error_code``,
  ``error_description``, ``error_source``, ``error_step``, ``error_reason``.
- A **synchronous API** error response uses the shorter keys ``code``,
  ``description``, ``source``, ``step``, ``reason``, plus two keys the
  webhook shape does not carry at all: ``field`` (the offending request
  field, when applicable) and ``metadata`` (a free-form object).

:class:`FailureSignal` accepts either shape through Pydantic's
``validation_alias`` / :class:`~pydantic.AliasChoices` mechanism and always
exposes the canonical, short field names, so every downstream phase (Phase 2
clustering onward) can work against one shape regardless of which Razorpay
surface produced the event.
"""

from collections.abc import Mapping

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from reflow.taxonomy.methods import ErrorCode, ErrorSource, ErrorStep


class FailureSignal(BaseModel):
    """Canonical, surface-independent representation of a payment failure.

    Instances are immutable (``model_config.frozen = True``): a
    ``FailureSignal`` represents a fact already reported by Razorpay, not a
    value downstream code should mutate in place.

    Attributes:
        code: The top-level error classification.
        description: Free-text, human-readable error description. This is
            the field that carries realistic variable noise (amounts, ids,
            VPAs, timestamps, ...) in the Phase 1 synthetic corpus, and that
            later phases mask before clustering.
        source: Which party/system the error is attributed to.
        step: Which step of the payment lifecycle the error occurred at.
        reason: The stable machine-readable reason code, drawn from the 114
            rows of the vendored Razorpay error-reasons spreadsheet (see
            :mod:`reflow.taxonomy.reasons`).
        field: Name of the specific request field that caused the error,
            when Razorpay's synchronous API supplies one. ``None`` for
            webhook-sourced signals, which never carry this key.
        metadata: Free-form additional context Razorpay's synchronous API
            sometimes attaches. ``None`` for webhook-sourced signals.
    """

    model_config = ConfigDict(frozen=True)

    code: ErrorCode = Field(validation_alias=AliasChoices("code", "error_code"))
    description: str = Field(validation_alias=AliasChoices("description", "error_description"))
    source: ErrorSource = Field(validation_alias=AliasChoices("source", "error_source"))
    step: ErrorStep = Field(validation_alias=AliasChoices("step", "error_step"))
    reason: str = Field(validation_alias=AliasChoices("reason", "error_reason"), min_length=1)
    field: str | None = None
    metadata: dict[str, object] | None = None

    @classmethod
    def from_webhook_payment_entity(cls, entity: Mapping[str, object]) -> "FailureSignal":
        """Build a signal from a webhook's ``payload.payment.entity`` object.

        Args:
            entity: The ``payload.payment.entity`` mapping from a
                ``payment.failed`` webhook body. Must contain
                ``error_code``, ``error_description``, ``error_source``,
                ``error_step``, and ``error_reason``.

        Returns:
            The normalised :class:`FailureSignal`.

        Raises:
            pydantic.ValidationError: If a required error key is missing or
                has an unrecognised value.
        """
        return cls.model_validate(entity)

    @classmethod
    def from_api_error(cls, error: Mapping[str, object]) -> "FailureSignal":
        """Build a signal from a synchronous API error object.

        Args:
            error: The ``error`` object from a synchronous Razorpay API
                error response, i.e. the value of the top-level ``"error"``
                key. Must contain ``code``, ``description``, ``source``,
                ``step``, and ``reason``; may additionally contain ``field``
                and ``metadata``.

        Returns:
            The normalised :class:`FailureSignal`.

        Raises:
            pydantic.ValidationError: If a required error key is missing or
                has an unrecognised value.
        """
        return cls.model_validate(error)
