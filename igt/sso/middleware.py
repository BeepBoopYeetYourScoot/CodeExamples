import logging
from functools import partial

import jwt
from aiohttp import web, hdrs

from ..aiohttp_jwt.utils import invoke, check_request
from ..sso.utils import has_permissions, decode_avanpost_jwt

logger = logging.getLogger(__name__)

_request_property = ...


def AvanpostJWTMiddleware(
        signing_key,
        request_property='payload',
        credentials_required=False,
        whitelist=tuple(),
        token_getter=None,
        is_revoked=None,
        store_token=False,
        auth_schema='Bearer',
):
    if not (signing_key and isinstance(signing_key, str)):
        raise RuntimeError(
            'secret or public key should be provided for correct work',
        )

    if not isinstance(request_property, str):
        raise TypeError('request_property should be a str')

    global _request_property

    _request_property = request_property

    @web.middleware
    async def jwt_middleware(request, handler):
        if request.method == hdrs.METH_OPTIONS:
            return await handler(request)

        if check_request(request, whitelist):
            return await handler(request)

        token = await invoke(partial(token_getter, request))

        if not token:
            raise web.HTTPUnauthorized(
                reason='Missing authorization token',
            )

        try:
            decoded = await decode_avanpost_jwt(token)
        except jwt.InvalidTokenError as exc:
            msg = 'Invalid authorization token, ' + str(exc)
            raise web.HTTPUnauthorized(reason=msg)

        if (callable(is_revoked)
                and await invoke(partial(is_revoked, request, token))):
            raise web.HTTPForbidden(reason='Token is revoked')

        request[request_property] = decoded

        if not await has_permissions(decoded):
            reason = "You have no rights to access the page."
            raise web.HTTPForbidden(reason=reason)

        if store_token and isinstance(store_token, str):
            request[store_token] = token

        return await handler(request)

    return jwt_middleware
