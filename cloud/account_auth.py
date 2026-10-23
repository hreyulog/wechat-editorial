"""Explicitly authorized ChatGPT cache transfer; credential values are never logged."""
import json
import re
import socket
import ssl


def validate_cache(value):
    if not isinstance(value, dict) or value.get('auth_mode') != 'chatgpt':
        raise ValueError('A ChatGPT account login cache is required')
    tokens = value.get('tokens')
    if not isinstance(tokens, dict) or any(not isinstance(tokens.get(k), str) or not tokens[k].strip()
            for k in ('access_token', 'refresh_token', 'id_token', 'account_id')):
        raise ValueError('The account login cache is incomplete')
    if value.get('OPENAI_API_KEY'):
        raise ValueError('Do not combine account credentials and an API key')
    return json.dumps({k: value[k] for k in ('auth_mode', 'tokens', 'last_refresh') if k in value}).encode()


def validate_model(value):
    if value is not None and (not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}', value)):
        raise ValueError('Invalid model name')
    return value


def safe_failure(text, auth):
    value = str(text)
    for token in auth.get('tokens', {}).values():
        if isinstance(token, str) and token:
            value = value.replace(token, '[REDACTED]')
    value = re.sub(r'\x1b\[[0-9;]*m', '', value)
    value = re.sub(r'https?://\S+', '[endpoint]', value)
    value = re.sub(r'eyJ[A-Za-z0-9_.-]{20,}', '[REDACTED]', value)
    return value[-1200:]


def account_network_probe():
    """Unauthenticated DNS/TLS diagnosis; never sends account credentials."""
    result={}
    for host in ('chatgpt.com','auth.openai.com'):
        stage='dns_or_tcp'
        try:
            with socket.create_connection((host,443),timeout=6) as raw:
                stage='tls'
                with ssl.create_default_context().wrap_socket(raw,server_hostname=host):pass
            result[host]={'tls':'connected'}
        except Exception as error:result[host]={'failed_stage':stage,'error_type':type(error).__name__}
    return result
