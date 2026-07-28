"""Authentication — the security layer at the edge.

This package is deliberately isolated from the messaging engine. Nothing here
imports :mod:`agent_inbox.mailbox`, :mod:`agent_inbox.rules`, or
:mod:`agent_inbox.house`, and none of those import this (a structural test
enforces it). Authentication proves *who* is calling; the messaging rules decide
*what* they may see. The two meet only at the API edge, where a verified caller
is resolved and handed down exactly as the ``X-Agent-Name`` header is today
(ADR 0007, ADR 0010).
"""
