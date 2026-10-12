"""The client side of V-cloak (M12): device key, DPoP proofs, key agreement, send and read.

Nothing in this package imports `vcloak.service`: the client is a second implementation of the
session protocol (RFC 9449, RFC 7638), so that the tests check the server against it.
"""
