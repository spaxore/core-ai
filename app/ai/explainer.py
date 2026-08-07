from app.ai.ollama_client import ask_ollama

AMOUNT_FIELDS = {"CHARGE_AMOUNT", "GE_AMOUNT", "AMOUNT", "DA_AMOUNT", "MAIN_DEB_AMOUNT"}
VOLUME_FIELDS = {"DATA_VOLUME"}

def format_evidence(evidence):
    if not evidence:
        return "Aucune donnee."
    lines = []
    for i, record in enumerate(evidence, start=1):
        lines.append(f"Enregistrement {i}:")
        for key, value in record.items():
            if key == "START_DATE" and value is not None:
                value = value.strftime("%d/%m/%Y")
            if key in AMOUNT_FIELDS and value is not None:
                value = f"{value} DT"
            if key in VOLUME_FIELDS and value is not None:
                value = f"{value} Ko"
            lines.append(f"  - {key}: {value}")
    return "\n".join(lines)

def explain_investigation(category, evidence):
    if not evidence:
        return "No matching records were found for this complaint. Further manual investigation may be required."

    formatted = format_evidence(evidence)

    prompt = f"""Tu es un assistant qui redige des explications factuelles courtes pour un employe de Tunisie Telecom.

Categorie de la reclamation: {category}
Donnees recuperees depuis la base de donnees:
{formatted}

Regles strictes (a respecter TOUTES sans exception):
1. Sortie: 2 a 3 phrases maximum, en prose continue. AUCUNE liste, AUCUN tiret, AUCUNE puce, AUCUN retour a la ligne.
2. N'ecris JAMAIS de phrase d'introduction ("Voici l'explication", "Voici les details", "Voici une explication", etc.). Commence directement par le fait.
3. Utilise UNIQUEMENT les valeurs listees ci-dessus. N'invente aucun detail absent des donnees.
4. Ne mentionne jamais le nom brut de la categorie ({category}) ni un mot qui le reformule (ex: interdiction de dire "DATA_USAGE", "il s'agit d'une expiration", "ceci est un cas de..."). Decris seulement les faits bruts: quel service, quel montant, quelle date.
5. Respecte exactement les unites deja presentes dans les donnees (DT, Ko). Ne les modifie jamais.
6. N'utilise pas les mots "reclamation", "remboursement", "demande" sauf s'ils apparaissent litteralement dans les donnees.
7. Ne pose aucune question, ne propose aucune aide supplementaire, ne termine pas par une formule de politesse.
8. N'utilise jamais les mots "enregistrement", "record" ou une numerotation ("Enregistrement 1", etc.) meme si ce mot apparait dans les donnees listees ci-dessus - ce sont des etiquettes internes, pas des faits a rapporter.
9. Ne recopie JAMAIS un code technique brut (par exemple: EVENT_TYPE, EVENT_STATUS, CALL_TYPE, ou des valeurs comme REV, SUCCESS, DATA, VAS) tel quel dans la phrase. Traduis-le systematiquement en francais courant et naturel. Exemple: EVENT_TYPE=REV devient "retablissement de credit", pas "REV". EVENT_STATUS=SUCCESS devient "effectue avec succes" ou "reussi", pas "SUCCESS".

Exemple de format attendu (style et longueur a reproduire, pas le contenu):
"Le client a ete facture 2,5 DT pour un volume de 512 Ko de donnees le 03/07/2026, sans roaming actif. Aucun autre evenement n'a ete enregistre durant la periode analysee."

Explication:
"""
    explanation = ask_ollama(prompt, temperature=0.2)
    return explanation
