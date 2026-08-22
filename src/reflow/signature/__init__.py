"""Phase 2 masking layer: strip variable tokens out of failure text.

This package is deliberately small and dependency-free: one pure,
deterministic function, :func:`~reflow.signature.mask.mask_description`,
shared by every candidate in the Phase 2 clustering bake-off
(:mod:`reflow.cluster`) so that the bake-off measures clustering quality
rather than masking quality. See :mod:`reflow.signature.mask` for the full
design rationale.
"""

from reflow.signature.mask import (
    ALL_PLACEHOLDERS,
    AMOUNT_PLACEHOLDER,
    BANK_PLACEHOLDER,
    CARD_BIN_PLACEHOLDER,
    CUSTOMER_ID_PLACEHOLDER,
    GENERIC_ID_PLACEHOLDER,
    KNOWN_INSTITUTIONS,
    ORDER_ID_PLACEHOLDER,
    PAYMENT_ID_PLACEHOLDER,
    RRN_PLACEHOLDER,
    TIMESTAMP_PLACEHOLDER,
    VPA_PLACEHOLDER,
    mask_description,
    mask_descriptions,
)

__all__ = [
    "ALL_PLACEHOLDERS",
    "AMOUNT_PLACEHOLDER",
    "BANK_PLACEHOLDER",
    "CARD_BIN_PLACEHOLDER",
    "CUSTOMER_ID_PLACEHOLDER",
    "GENERIC_ID_PLACEHOLDER",
    "KNOWN_INSTITUTIONS",
    "ORDER_ID_PLACEHOLDER",
    "PAYMENT_ID_PLACEHOLDER",
    "RRN_PLACEHOLDER",
    "TIMESTAMP_PLACEHOLDER",
    "VPA_PLACEHOLDER",
    "mask_description",
    "mask_descriptions",
]
