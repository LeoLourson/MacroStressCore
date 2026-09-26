"""Snapshot kinds the market plugin declares; every family priced at market reads them."""

#: The spot rate of a currency pair ``CCY/BASE``: units of ``BASE`` per unit of ``CCY``.
FX_RATE = "fx_rate"
#: The market price of an instrument, in its currency per unit.
PRICE = "price"
