import requests


OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_BASE_URL = "http://localhost:11434"


class OllamaUnavailableError(Exception):
    """
    Raised when Ollama itself can't be reached (not running, wrong port,
    etc.) -- distinct from a normal request failure so callers (the
    /classify and /investigate routes) can return a clear 503 instead of
    letting requests.exceptions.ConnectionError bubble up as an unhandled
    500. Previously unhandled entirely: closing Ollama produced a plain
    500 Internal Server Error with no JSON body, which the frontend's
    response.json() then failed to parse, surfacing a confusing
    "Unexpected token 'I', 'Internal S'... is not valid JSON" error
    instead of the actual, simple cause.
    """
    pass


def ask_ollama(prompt, temperature=0.2):

    payload = {
        "model": "llama3.1",
        "prompt": prompt,
        "stream": False,
        "options": { "temperature": temperature }
    }

    try:
        response = requests.post(
            OLLAMA_URL,
            json=payload,
            timeout=90
        )
    except requests.exceptions.ConnectionError:
        raise OllamaUnavailableError(
            "Impossible de contacter Ollama -- le service LLM doit être actif pour lancer une investigation."
        )

    result = response.json()

    return result["response"]


def is_ollama_online():
    try:
        requests.get(OLLAMA_BASE_URL, timeout=3)
        return True
    except requests.exceptions.RequestException:
        return False

