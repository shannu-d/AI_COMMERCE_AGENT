"""The commerce evaluation suite (M15).

Everything a case asserts about a product — its price, its SKU, its stock, what
it is compatible with — is read from the database at run time by
`catalog_facts.py`. No expectation in `commerce_eval_cases.json` names a price
or a stock level, because a hardcoded fact is a fact that goes stale the moment
the catalogue moves and then quietly grades the wrong thing.
"""
