"""Realistic, noisy description rendering for synthetic failure events.

Phase 2 masks variable tokens (amounts, ids, VPAs, bank names, timestamps,
RRNs, ...) out of ``description`` before clustering. If every event for a
given reason carried an identical description, that masking step would
have nothing to do, and any clustering result computed downstream would be
an artefact of string-matching rather than of genuine root-cause discovery.
This module is what makes each event's description different from its
siblings while still being recognisably about the same underlying reason
(or, for catch-all reasons, the same underlying *latent sub-cause* -- see
:mod:`reflow.corpus.reasons`).

Two rendering paths exist:

- **Narrow reasons** (the ~102 of 110 unique vendored reasons that describe
  one specific, unambiguous failure mechanism): the description is built
  from that reason's own vendored ``Explanation`` text plus an interpolated
  clause of noise tokens relevant to the payment method. Because a narrow
  reason genuinely has only one underlying cause, it is correct -- not a
  simplification -- for its post-masking residual to be near-identical
  across events; :mod:`reflow.corpus.reasons` deliberately does not
  manufacture fake sub-cause variety here.
- **Catch-all reasons** (``payment_failed``, ``server_error``,
  ``bank_technical_error``, ``gateway_technical_error``, ``card_declined``,
  ``payment_declined``, ``issuer_technical_error``, ``debit_declined``):
  the description is built from one of several hand-authored latent
  sub-cause templates (see :data:`reflow.corpus.reasons.CATCH_ALL_SUBCAUSES`)
  that share vocabulary but describe genuinely different mechanisms, so
  that whether they separate under clustering depends on masking quality
  rather than on trivially distinct wording.

On top of both paths, a minority of reasons/sub-causes also carry an
alternate *surface* wording -- either a paraphrase (different vocabulary,
same meaning) or a clause reordering (same vocabulary, different order),
each labelled ``description_variant`` on the generated event. This is what
the second Phase 1 corpus-design addendum calls for: a fixed-depth parser
like Drain3, exact-match template hashing, and TF-IDF bag-of-words each
fail differently on paraphrase/reorder pairs of the *same* ground truth,
and the corpus needs to actually contain such pairs for that difference to
be measurable at all. See :data:`reflow.corpus.reasons.NARROW_REASON_ALT_PHRASINGS`
and :class:`reflow.corpus.reasons.LatentSubcause.paraphrase`.

Known simplification, stated plainly rather than hidden: the noise-token
vocabulary reuses :data:`reflow.corpus.tokens.INDIAN_BANKS` as a stand-in
"counterparty institution" name even for Wallet and Cardless EMI events,
where the real counterparty would be a wallet provider or EMI financier
rather than a bank. Modelling separate institution-name pools per method
would improve realism marginally but was not worth the added complexity
for a token whose only job is to be masked back out in Phase 2.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime

from reflow.corpus import tokens as tok
from reflow.corpus.reasons import NARROW_REASON_ALT_PHRASINGS, LatentSubcause
from reflow.taxonomy.methods import PaymentMethod

ALT_PHRASING_PROBABILITY: float = 0.4
"""Probability that a narrow reason with an entry in
:data:`reflow.corpus.reasons.NARROW_REASON_ALT_PHRASINGS` renders using
that alternate wording instead of its canonical, explanation-derived
sentence. Kept a minority so the canonical wording -- the "clean templated
message" baseline -- remains the common case even for these reasons."""

_SUBCAUSE_CANONICAL_WEIGHT: float = 0.6
"""Probability weight given to a sub-cause's canonical ``template`` over
its ``paraphrase``, when one exists."""


@dataclass(frozen=True, slots=True)
class NoiseTokens:
    """One event's worth of realistic, randomly drawn variable tokens.

    Attributes:
        payment_id: Razorpay-style payment id.
        order_id: Razorpay-style order id.
        amount_paise: Transaction amount, in paise.
        created_at: Event timestamp.
        bank: A bank/institution name (see module docstring simplification).
        vpa: A synthetic UPI VPA.
        card_bin: A synthetic 6-digit card BIN.
        rrn: A synthetic 12-digit Retrieval Reference Number.
    """

    payment_id: str
    order_id: str
    amount_paise: int
    created_at: datetime
    bank: str
    vpa: str
    card_bin: str
    rrn: str

    def as_format_mapping(self) -> dict[str, str]:
        """Render every token as a display-ready string for templating.

        Returns:
            A mapping suitable for ``str.format_map``, keyed by the
            placeholder names used across narrow and catch-all templates
            (``payment_id``, ``order_id``, ``amount_display``, ``bank``,
            ``vpa``, ``card_bin``, ``rrn``, ``timestamp_display``).
        """
        return {
            "payment_id": self.payment_id,
            "order_id": self.order_id,
            "amount_display": f"Rs.{self.amount_paise / 100:.2f}",
            "bank": self.bank,
            "vpa": self.vpa,
            "card_bin": self.card_bin,
            "rrn": self.rrn,
            "timestamp_display": self.created_at.isoformat(timespec="seconds"),
        }


def generate_noise_tokens(
    rng: random.Random, created_at: datetime, amount_paise: int
) -> NoiseTokens:
    """Draw a fresh, deterministic set of noise tokens for one event.

    Args:
        rng: Deterministic random source.
        created_at: The event's timestamp, reused verbatim (not redrawn) so
            that the description's displayed timestamp matches the event's
            actual ``created_at``.
        amount_paise: The event's amount, reused verbatim so that the
            displayed amount matches the event's actual ``amount``.

    Returns:
        A populated :class:`NoiseTokens`.
    """
    return NoiseTokens(
        payment_id=tok.random_id(rng, "pay"),
        order_id=tok.random_id(rng, "order"),
        amount_paise=amount_paise,
        created_at=created_at,
        bank=tok.random_bank_name(rng),
        vpa=tok.random_vpa(rng),
        card_bin=tok.random_card_bin(rng),
        rrn=tok.random_rrn(rng),
    )


_METHOD_CLAUSE_TEMPLATES: dict[PaymentMethod, str] = {
    PaymentMethod.CARD: " (payment {payment_id}, order {order_id}, {amount_display}, "
    "card BIN {card_bin}, at {timestamp_display})",
    PaymentMethod.UPI: " (payment {payment_id}, order {order_id}, {amount_display}, "
    "VPA {vpa}, RRN {rrn}, at {timestamp_display})",
    PaymentMethod.NETBANKING: " (payment {payment_id}, order {order_id}, "
    "{amount_display}, via {bank}, at {timestamp_display})",
    PaymentMethod.WALLET: " (payment {payment_id}, order {order_id}, {amount_display}, "
    "at {timestamp_display})",
    PaymentMethod.CARDLESS_EMI: " (payment {payment_id}, order {order_id}, "
    "{amount_display}, at {timestamp_display})",
    PaymentMethod.EMANDATE: " (payment {payment_id}, order {order_id}, {amount_display}, "
    "via {bank}, at {timestamp_display})",
}
"""Per-method trailing clause appended to a narrow reason's base explanation
sentence. Each clause always carries ``payment_id``/``order_id``/``amount``/
``timestamp`` (present on every event regardless of method) plus whichever
method-specific identifier (card BIN, VPA + RRN, or bank) is realistic for
that method."""


def render_narrow_description(
    reason: str,
    explanation: str,
    method: PaymentMethod,
    noise: NoiseTokens,
    rng: random.Random,
) -> tuple[str, str]:
    """Render a description for a narrow (single-sub-cause) reason.

    Args:
        reason: The reason code, used to look up an optional alternate
            phrasing in :data:`reflow.corpus.reasons.NARROW_REASON_ALT_PHRASINGS`.
        explanation: The reason's vendored ``Explanation`` text.
        method: The payment method of the event, which selects which
            noise tokens are appended.
        noise: The event's drawn noise tokens.
        rng: Deterministic random source, used only to decide whether to
            use the canonical or an alternate phrasing.

    Returns:
        A tuple of (rendered description, variant label). The variant
        label is ``"canonical"`` unless ``reason`` has an alternate
        phrasing and it was selected, in which case it is
        ``"paraphrase_wording"`` or ``"paraphrase_reordered"``.
    """
    alt = NARROW_REASON_ALT_PHRASINGS.get(reason)
    if alt is not None and rng.random() < ALT_PHRASING_PROBABILITY:
        base_sentence = alt.text
        variant_label = alt.label
    else:
        base_sentence = explanation.split(". ")[0].rstrip(".") + "."
        variant_label = "canonical"
    clause = _METHOD_CLAUSE_TEMPLATES[method].format_map(noise.as_format_mapping())
    return f"{base_sentence}{clause}", variant_label


def render_subcause_description(
    subcause: LatentSubcause, noise: NoiseTokens, rng: random.Random
) -> tuple[str, str]:
    """Render a description for one latent sub-cause of a catch-all reason.

    Args:
        subcause: The hand-authored sub-cause (see
            :data:`reflow.corpus.reasons.CATCH_ALL_SUBCAUSES`), whose
            ``template`` and optional ``paraphrase`` contain ``str.format``
            placeholders drawn from :meth:`NoiseTokens.as_format_mapping`.
        noise: The event's drawn noise tokens.
        rng: Deterministic random source, used only to decide whether to
            use the canonical template or the paraphrase, when one exists.

    Returns:
        A tuple of (rendered description, variant label), following the
        same labelling convention as :func:`render_narrow_description`.
    """
    if subcause.paraphrase is not None and rng.random() >= _SUBCAUSE_CANONICAL_WEIGHT:
        text = subcause.paraphrase.text
        variant_label = subcause.paraphrase.label
    else:
        text = subcause.template
        variant_label = "canonical"
    return text.format_map(noise.as_format_mapping()), variant_label
