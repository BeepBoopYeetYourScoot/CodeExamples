from forest_gateway.settings import get_config

config = get_config()

ISSUER = config.avanpost.issuer

AUTHORIZATION_REDIRECT_URL = config.avanpost.authorization_redirect_url
LOCALHOST_REDIRECT_URL = config.avanpost.localhost_redirect_url
TOKEN_REDIRECT_URL = config.avanpost.token_redirect_url
HOST = config.avanpost.host
CLIENT_ID = config.avanpost.client_id
CLIENT_SECRET = config.avanpost.client_secret
USERINFO_URL = f"{ISSUER}/oauth2/userinfo"

SCOPES = config.avanpost.scopes
PARMA_ML_GROUP_NAME = config.avanpost.parma_ml_group_name
DEFAULT_HASH_ALGORITHM = config.avanpost.default_hash_algorithm

AUTHORIZATION_URL = (
    f"{ISSUER}/"
    "oauth2/authorize"
    "?response_type=code"
    "&client_id={client_id}"
    "&scope={scopes}"
    "&redirect_uri={redirect_url}"
    "&code_challenge_method=S256"
    "&code_challenge={code_challenge}"
    "&state={state}"
)
TOKEN_URL = f"{ISSUER}/oauth2/token"
PUBLIC_KEY_URL = f'{ISSUER}/oauth2/public_keys'
TOKEN_REVOCATION_URL = f'{ISSUER}/oauth2/token/revoke'

CODE_VERIFIER_REDIS_KEY = "forest:sso:avanpost:code_verifier:{state}"
TOKEN_REDIS_KEY = 'forest:sso:token:{access_token}'

LOCALHOST_REDIRECT_URL = config.avanpost.localhost_redirect_url
