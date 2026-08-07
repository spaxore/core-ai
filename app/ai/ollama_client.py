import requests


OLLAMA_URL = "http://localhost:11434/api/generate"


def ask_ollama(prompt, temperature=0.2):

    payload = {
        "model": "llama3.1",
        "prompt": prompt,
        "stream": False,
        "options": { "temperature": temperature }
    }

    response = requests.post(
        OLLAMA_URL,
        json=payload
    )

    result = response.json()

    return result["response"]

