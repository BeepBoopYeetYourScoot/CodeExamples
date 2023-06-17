import base64
import hashlib
import http
import json
import os
import re
from typing import Union, Dict

import aiohttp
import aioredis
import jwt.algorithms
import requests
from aiohttp import web
from aiohttp.web_request import Request

from forest_gateway.logger import gateway_logger
from forest_gateway.users.sso import avanpost


async def get_code_verifier() -> str:
    """
    Return random string of n characters
    """
    code_verifier = base64.urlsafe_b64encode(os.urandom(40)).decode('utf-8')
    return re.sub('[^a-zA-Z0-9]+', '', code_verifier)


async def get_code_challenge(code_verifier: str) -> str:
    code_challenge = hashlib.sha256(code_verifier.encode('utf-8')).digest()
    code_challenge = base64.urlsafe_b64encode(code_challenge).decode('utf-8')
    return code_challenge.replace('=', '')


async def set_code_verifier(code_verifier: str,
                            redis_conn: aioredis.Redis,
                            state: str
                            ) -> None:
    code_verifier_key = avanpost.CODE_VERIFIER_REDIS_KEY.format(state=state)
    await redis_conn.set(key=code_verifier_key, value=code_verifier)
    assert await redis_conn.exists(code_verifier_key)


async def revoke_code_verifier(redis_conn: aioredis.Redis, state):
    code_verifier_key = avanpost.CODE_VERIFIER_REDIS_KEY.format(state=state)
    await redis_conn.delete(code_verifier_key)
    assert not await redis_conn.exists(code_verifier_key)


async def has_permissions(token: dict):
    return any(group.get('name') == avanpost.PARMA_ML_GROUP_NAME
               for group in token.get('groups'))


async def set_access_token(redis_conn: aioredis.Redis,
                           access_token: Union[str, bytes],
                           expires_in=0
                           ) -> None:
    gateway_logger.debug(f"Setting access token: {access_token=:.50}")
    await redis_conn.set(key=avanpost.TOKEN_REDIS_KEY,
                         value=access_token,
                         expire=expires_in)


async def set_refresh_token(redis_conn, access_token, refresh_token):
    gateway_logger.debug(f"Setting refresh token: {refresh_token=:.50}")
    access_token_key = f"{avanpost.TOKEN_REDIS_KEY}:{access_token}"
    await redis_conn.set(key=access_token_key, value=refresh_token)


async def get_public_key(token: Union[str, bytes]):
    # for JWKS that contain multiple JWK
    response = requests.get(avanpost.PUBLIC_KEY_URL)

    gateway_logger.debug(f"Requesting public keys. "
                         f"URL: {response.request.url}"
                         f"Headers: {response.request.headers}"
                         f"Body: {response.request.body}")
    assert response.status_code == http.HTTPStatus.OK, response.reason

    public_keys = {}

    for jwk in response.json()['keys']:
        kid = jwk['kid']
        public_keys[kid] = jwt.algorithms.RSAAlgorithm.from_jwk(
            json.dumps(jwk))

    if not token:
        return public_keys['1']

    kid = jwt.get_unverified_header(token)['kid']
    return public_keys[kid]


async def is_revoked(request: Request, token: bytes):
    redis_conn = request.app['redis']
    await redis_conn.exists(f"{avanpost.TOKEN_REDIS_KEY}:{token}")


async def generate_state():
    return await get_code_verifier()


async def request_exchange(pkce_code: Union[str, bytes],
                           code_verifier: Union[str, bytes]
                           ) -> Dict:
    """
    Промежуточный метод, позволяет не забивать голову форматами запроса
    и ответа.
    """
    async with aiohttp.ClientSession() as session:
        async with await session.post(url=avanpost.TOKEN_URL, json={
            "grant_type": "authorization_code",
            "client_id": avanpost.CLIENT_ID,
            "redirect_uri": avanpost.AUTHORIZATION_REDIRECT_URL,
            "code": str(pkce_code),
            "code_verifier": str(code_verifier),
        }) as response:
            gateway_logger.debug(
                f"Requested PKCE. "
                f"Request URL: {response.request_info.url} \n"
                f"Request Headers: {response.request_info.headers} \n"
                f"Request Body: {response.request_info} \n"
                f"PKCE Code: {pkce_code} \n"
                f"Code verifier: {code_verifier}")
            return await json_or_raise_for_status(response)


async def request_refresh(refresh_token) -> Dict:
    async with aiohttp.ClientSession() as session:
        async with await session.post(url=avanpost.TOKEN_URL, json={
            "grant_type": "refresh_token",
            "client_id": avanpost.CLIENT_ID,
            "redirect_uri": avanpost.AUTHORIZATION_REDIRECT_URL,
            "refresh_token": str(refresh_token)
        }) as response:
            gateway_logger.debug(f"Requested Access Token refresh. "
                                 f"Request Headers: "
                                 f"{response.request_info.headers} \n"
                                 f"Request Body: {response.request_info}")
            return await json_or_raise_for_status(response)


async def json_or_raise_for_status(response: aiohttp.ClientResponse) -> Dict:
    try:
        response_dict = await response.json()
    except json.JSONDecodeError as e:
        raise web.HTTPBadRequest(reason=str(e))
    gateway_logger.debug(f"Got response: {response_dict}")
    if response_dict.get('access_token'):
        return response_dict
    if response_dict.get('error') is not None:
        raise web.HTTPBadRequest(reason=response_dict)
    response.raise_for_status()
    return response_dict


async def request_json_web_keys(jwks_uri=avanpost.PUBLIC_KEY_URL):
    async with aiohttp.ClientSession() as session:
        async with await session.get(url=jwks_uri) as response:
            response.raise_for_status()
            return await response.json()


async def request_token_info(token, userinfo_url=avanpost.USERINFO_URL):
    headers = {"Authorization": f"Bearer {token}"}
    async with aiohttp.ClientSession() as session:
        async with await session.get(
                url=userinfo_url,
                headers=headers
        ) as response:
            response.raise_for_status()
            return await response.json()


async def decode_avanpost_jwt(token: str):
    algorithms = [avanpost.DEFAULT_HASH_ALGORITHM]
    info = await request_token_info(token)
    public_key = await request_public_key(token)

    return jwt.decode(token,
                      public_key,
                      algorithms=algorithms,
                      issuer=avanpost.ISSUER,
                      audience=info['aud'])


async def request_public_key(token):
    jwks = await request_json_web_keys()
    keys = {jwk['kid']: jwk for jwk in jwks['keys']}
    kid = jwt.get_unverified_header(token)['kid']
    return jwt.algorithms.RSAAlgorithm.from_jwk(keys[kid])


async def has_token_expired(redis: aioredis.Redis,
                            access_token_key: str
                            ) -> bool:
    ttl = await redis.ttl(access_token_key)
    if ttl == -2:
        # Key does not exist
        raise KeyError(f"Key {access_token_key} does not exist")
    elif ttl == -1:
        # Key exists but never expires
        return False
    else:
        # Check if the TTL is greater than 0
        return ttl <= 0
