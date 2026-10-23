"""Explicit cloud model provider; never imports desktop login material."""
import json
from urllib.parse import urlsplit


def validate(value):
    if not isinstance(value,dict) or set(value)!={'base_url','model','api_key'}:
        raise ValueError('Model configuration requires base_url, model and api_key')
    if any(not isinstance(value[k],str) or not value[k].strip() or '\n' in value[k] or '\r' in value[k] for k in value):
        raise ValueError('Model configuration contains empty or multiline fields')
    parsed=urlsplit(value['base_url'])
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Model base URL must be HTTPS without credentials, query or fragment')
    if value['model']=='YOUR_MODEL' or value['api_key']=='YOUR_KEY':
        raise ValueError('Replace model configuration placeholders before deployment')
    return value


def provider_toml(base_url,model):
    # The key stays in the service environment; only its variable name is written.
    return '\n'.join(['model = '+json.dumps(model),'model_provider = "cloud_model"',
        '[model_providers.cloud_model]','name = "Cloud model"','base_url = '+json.dumps(base_url),
        'env_key = "EDITORIAL_MODEL_API_KEY"','wire_api = "responses"','requires_openai_auth = false',''])
