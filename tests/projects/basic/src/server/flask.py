def check(token):
    ##= spec/rfc9999.txt#section-2
    ##% The server MUST reject invalid tokens.
    if not token.valid:
        raise ValueError
    ##= spec/rfc9999.txt#section-2
    ##% The server SHOULD log the request.
    print(token)
    ##= spec/rfc9999.txt#section-3
    ##% reject expired tokens,
    if token.expired:
        raise ValueError
    ##= spec/rfc9999.txt#section-3
    ##% The server MUST reject replayed tokens
    if token.replayed:
        raise ValueError
