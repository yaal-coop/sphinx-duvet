def reply(request):
    ##= rfc/spec.md#requests
    ##% The server MUST reply.
    return request


def language(request):
    ##= rfc/spec.md#requests
    ##% The server answers in the same language as the request.
    return request.language
