"""Vendor-neutral replay market and virtual brokerage API.

The General API never generates trading decisions. It publishes recorded market
events, accepts orders created by connected bots, emulates broker responses, and
records an attributable audit trail.
"""

from .service import GeneralBrokerService

__all__ = ["GeneralBrokerService"]
