def check(token):
    ##= spec/rfc9999.txt#section-2
    ##% The server MUST reject invalid tokens.
    if not token.valid:
        raise ValueError
    ##= spec/rfc9999.txt#section-2
    ##= type=todo
    ##% The server SHOULD log the request.
