import http
from typing import Dict

import aiohttp
import requests
import shielded  # prevents POST controllers from cancellation
from aiohttp import web

from . import avanpost, utils
from .exceptions import TokenAlreadyRevoked
from .logger import gateway_logger
from .utils import (generate_state,
                    get_code_verifier,
                    set_code_verifier,
                    get_code_challenge,
                    revoke_code_verifier,
                    set_access_token,
                    set_refresh_token,
                    request_exchange,
                    request_refresh, has_token_expired
                    )


async def login(request):
    """Issue code verifier & state for PKCE flow"""
    state = await generate_state()
    code_verifier = await get_code_verifier()
    gateway_logger.debug(f"Authenticating user with \n"
                         f"State: {state} \n"
                         f"Code verifier: {code_verifier}")
    await set_code_verifier(code_verifier, request.app['redis'], state)
    raise web.HTTPFound(
        avanpost.AUTHORIZATION_URL.format(
            scopes=avanpost.SCOPES,
            redirect_url=avanpost.AUTHORIZATION_REDIRECT_URL,
            code_challenge=await get_code_challenge(code_verifier),
            client_id=avanpost.CLIENT_ID,
            state=state,
        )
    )


async def exchange_code_for_token(pkce_code: str,
                                  code_verifier: str,
                                  ) -> Dict:
    return await request_exchange(pkce_code, code_verifier)


async def refresh_access_token(request: aiohttp.web.Request) -> Dict:
    redis_conn = request.app['redis']
    access_token, refresh_token = (request['payload']['access_token'],
                                   request['payload']['refresh_token'])
    access_token_key = (avanpost.TOKEN_REDIS_KEY.format(access_token))

    if await has_token_expired(redis_conn, access_token_key):
        return await request_refresh(refresh_token)


async def sso_callback(request):
    """
    Address to exchange code_verifier for access_token
    """
    redis_conn, code, state = (request.app['redis'],
                               request.query.get('code'),
                               request.query.get('state'))
    code_verifier_key = avanpost.CODE_VERIFIER_REDIS_KEY.format(state=state)
    code_verifier = await redis_conn.get(code_verifier_key,
                                         encoding='utf-8')

    gateway_logger.debug(f"Code: {code}, \n"
                         f"Code verifier: {code_verifier} \n"
                         f"State: {state}")

    if not code:
        raise web.HTTPBadRequest(reason="PKCE code required")

    response_dict = await exchange_code_for_token(code, code_verifier)
    access_token = response_dict.get('access_token')
    refresh_token = response_dict.get('refresh_token')

    await revoke_code_verifier(redis_conn, state)
    await set_access_token(redis_conn,
                           access_token,
                           response_dict.get('expires_in'))
    await set_refresh_token(redis_conn,
                            access_token,
                            refresh_token)

    assert await redis_conn.exists(
        f"{avanpost.TOKEN_REDIS_KEY}:{access_token}")
    return web.HTTPFound(
        avanpost.TOKEN_REDIRECT_URL.format(access_token=access_token,
                                           refresh_token=refresh_token)
    )


@shielded
async def logout(request):
    """
    Logout user by revoking the authorization token in the request

    If a person somehow manages to pass the correct state from frontend,
    it will log the user out.
    """
    redis_conn, sso_token = request.app['redis'], request['sso_token']

    token_key = f"{avanpost.TOKEN_REDIS_KEY}:{sso_token}"
    token = await redis_conn.get(token_key)

    if token is None:
        raise TokenAlreadyRevoked

    response = requests.post(avanpost.TOKEN_REVOCATION_URL, data={
        'client_id': avanpost.CLIENT_ID,
        'client_secret': avanpost.CLIENT_SECRET,
        'token': token,
    })

    if response.status_code != http.HTTPStatus.OK:
        raise ValueError(
            f'Could not revoke token from issuer. Issuer response: '
            f'{response.json()}')

    assert await redis_conn.exists(token_key)
    await redis_conn.delete(token_key)
    assert not await redis_conn.exists(token_key)
    return web.HTTPNoContent()


@shielded
async def refresh_tokens(request: aiohttp.web.Request):
    redis_conn = request.app['redis']

    refresh_token_response = await refresh_access_token(request)
    access_token, refresh_token, expires_in = (
        refresh_token_response.get('access_token'),
        refresh_token_response.get('refresh_token'),
        refresh_token_response.get('expires_in')
    )

    await utils.set_access_token(redis_conn,
                                 access_token,
                                 expires_in)
    await utils.set_refresh_token(redis_conn,
                                  access_token,
                                  refresh_token)
    return web.json_response({
        "access_token": access_token,
        "refresh_token": refresh_token
    })
