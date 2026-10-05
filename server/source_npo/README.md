# VodLoft NPO Source

This package is the complete NPO Start integration. Core VodLoft code only
registers it as a trusted Source runtime; NPO-specific behavior stays here.

Resolution is API-first. The Source uses NPO Start's own domain endpoints for
series, seasons, programs, search, player tokens and stream leases. If the
metadata endpoints disappear or return an unknown shape, a bounded crawler
falls back to NPO's rendered pages, Next.js hydration data, JSON-LD and
same-series links. The crawler is deliberately restricted to NPO Start URLs,
page/response limits and public network destinations.

An optional Source connection can store an NPO account email and password.
Credentials are sent only to NPO's own sign-in flow and never returned through
the Source protocol. Authenticated connections can discover premium catalogue
results and request streams using the logged-in NPO session.

The Source does not bypass DRM. If NPO returns a Widevine/FairPlay-protected
representation, the operation reports `unsupported_format`. Unencrypted
representations can be streamed or acquired normally.
