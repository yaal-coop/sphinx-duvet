def check_reply(server):
    ##= rfc/spec.md#requests
    ##% The server MUST reply.
    assert server.reply("request")
