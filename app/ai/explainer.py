import re

from app.ai.ollama_client import ask_ollama

# DATA_VOLUME is stored in KB (see app/services/data_service.py for how
# this was established from real imported data); summaries report GB
# since that's what complaints state.
KB_PER_GB = 1024 * 1024


def _bucket_identity(row):
    return (row.get("_SOURCE"), row.get("DA_VALUE") or row.get("FLEX_FLD2") or row.get("LOAN_ID"))


def _is_heterogeneous_cross_source(evidence):
    """
    cross_source_search.py tags every matched row with "_SOURCE" when a
    complaint's stated cause didn't pan out and a different table
    explained it instead. A single-row match (single_transaction/
    balance_swing) from one source is still one specific bucket -- the
    normal per-table shape below already describes it accurately. Only
    a full_period_total spanning multiple distinct buckets/sources is
    the case the per-table shapes get wrong (claiming one bucket's GB
    total when the real evidence is an aggregate across several
    unrelated buckets) -- that's the only case that needs its own shape.
    """
    if not evidence or not evidence[0].get("_SOURCE"):
        return False
    return len(set(_bucket_identity(r) for r in evidence)) > 1


def summarize_evidence(category, evidence):
    if not evidence:
        return None

    first = evidence[0]

    if _is_heterogeneous_cross_source(evidence):
        total_charged = sum(r.get("CHARGE_AMOUNT") or 0 for r in evidence)
        dates = [r["START_DATE"] for r in evidence if r.get("START_DATE")]
        oldest = min(dates) if dates else None
        newest = max(dates) if dates else None
        sources = sorted(set(r.get("_SOURCE") for r in evidence if r.get("_SOURCE")))

        return {
            "shape": "cross_source",
            "event_count": len(evidence),
            "total_charged": round(total_charged, 3),
            "period_start": oldest.strftime("%d/%m/%Y") if oldest else None,
            "period_end": newest.strftime("%d/%m/%Y") if newest else None,
            "sources": sources,
        }

    if "DATA_VOLUME" in first and "FLEX_FLD2" in first:
        total_volume_gb = sum(r.get("DATA_VOLUME") or 0 for r in evidence) / KB_PER_GB
        total_charged = sum(r.get("CHARGE_AMOUNT") or 0 for r in evidence)
        dates = [r["START_DATE"] for r in evidence if r.get("START_DATE")]
        oldest = min(dates) if dates else None
        newest = max(dates) if dates else None

        return {
            "shape": "data_usage",
            "da_value": first.get("FLEX_FLD2"),
            "session_count": len(evidence),
            "total_volume_gb": round(total_volume_gb, 2),
            "total_charged": round(total_charged, 3),
            "period_start": oldest.strftime("%d/%m/%Y") if oldest else None,
            "period_end": newest.strftime("%d/%m/%Y") if newest else None,
        }

    if "LOAN_ID" in first and "CHARGE_AMOUNT" in first:
        total_charged = sum(r.get("CHARGE_AMOUNT") or 0 for r in evidence)
        dates = [r["START_DATE"] for r in evidence if r.get("START_DATE")]
        oldest = min(dates) if dates else None
        newest = max(dates) if dates else None
        loan_ids = sorted(set(r.get("LOAN_ID") for r in evidence if r.get("LOAN_ID")))

        return {
            "shape": "sos_credit",
            "event_count": len(evidence),
            "loan_count": len(loan_ids),
            "total_charged": round(total_charged, 3),
            "period_start": oldest.strftime("%d/%m/%Y") if oldest else None,
            "period_end": newest.strftime("%d/%m/%Y") if newest else None,
        }

    if "KEYWORD" in first and "CHARGE_AMOUNT" in first:
        total_charged = sum(r.get("CHARGE_AMOUNT") or 0 for r in evidence)
        dates = [r["START_DATE"] for r in evidence if r.get("START_DATE")]
        oldest = min(dates) if dates else None
        newest = max(dates) if dates else None
        services = sorted(set(r.get("KEYWORD") for r in evidence if r.get("KEYWORD")))

        return {
            "shape": "sms_vas",
            "event_count": len(evidence),
            "total_charged": round(total_charged, 3),
            "period_start": oldest.strftime("%d/%m/%Y") if oldest else None,
            "period_end": newest.strftime("%d/%m/%Y") if newest else None,
            "services": services,
        }

    if "STATUS_DETAILS" in first and "SERVICE_CODE" in first:
        dates = [r["START_DATE"] for r in evidence if r.get("START_DATE")]
        oldest = min(dates) if dates else None
        newest = max(dates) if dates else None
        reasons = sorted(set(r.get("STATUS_DETAILS") for r in evidence if r.get("STATUS_DETAILS")))

        return {
            "shape": "renewal_failure",
            "attempt_count": len(evidence),
            "reasons": reasons,
            "period_start": oldest.strftime("%d/%m/%Y") if oldest else None,
            "period_end": newest.strftime("%d/%m/%Y") if newest else None,
        }

    # Checked before the generic DA_VALUE+CHARGE_AMOUNT shape below: these
    # rows also carry both keys, but CHARGE_AMOUNT is always 0 here (the
    # real adjustment value lives in DA_AMOUNT/DEDICTATED_AMNT, a field
    # unique to this table) -- falling through to that branch would
    # silently produce "debited 0 DT", actively misrepresenting the finding.
    if "DA_AMOUNT" in first and "DEDICTATED_AMNT" in first:
        dates = [r["START_DATE"] for r in evidence if r.get("START_DATE")]
        oldest = min(dates) if dates else None
        newest = max(dates) if dates else None
        total_da_amount = sum(r.get("DA_AMOUNT") or 0 for r in evidence)

        return {
            "shape": "da_adjustment",
            "adjustment_count": len(evidence),
            "total_da_amount": round(total_da_amount, 3),
            "period_start": oldest.strftime("%d/%m/%Y") if oldest else None,
            "period_end": newest.strftime("%d/%m/%Y") if newest else None,
        }

    if "DA_VALUE" in first and "CHARGE_AMOUNT" in first:
        total_charged = sum(r.get("CHARGE_AMOUNT") or 0 for r in evidence)
        dates = [r["START_DATE"] for r in evidence if r.get("START_DATE")]
        oldest = min(dates) if dates else None
        newest = max(dates) if dates else None
        da_value = first.get("DA_VALUE")

        oldest_row = min(evidence, key=lambda r: r.get("START_DATE") or newest) if dates else None
        newest_row = max(evidence, key=lambda r: r.get("START_DATE") or oldest) if dates else None

        balance_before = oldest_row.get("DA_VALUE_BEFORE") if oldest_row else None
        balance_after = newest_row.get("DA_VALUE_AFTER") if newest_row else None

        return {
            "shape": "da_transactions",
            "da_value": da_value,
            "transaction_count": len(evidence),
            "total_charged": round(total_charged, 3),
            "period_start": oldest.strftime("%d/%m/%Y") if oldest else None,
            "period_end": newest.strftime("%d/%m/%Y") if newest else None,
            "balance_before": balance_before,
            "balance_after": balance_after,
        }

    if "AMOUNT" in first or "DUREE_MINUTES" in first:
        total_amount = sum(r.get("AMOUNT") or 0 for r in evidence)
        total_minutes = sum(r.get("DUREE_MINUTES") or 0 for r in evidence)
        dates = [r["START_DATE"] for r in evidence if r.get("START_DATE")]
        oldest = min(dates) if dates else None
        newest = max(dates) if dates else None

        return {
            "shape": "daily_usage",
            "day_count": len(evidence),
            "total_amount": round(total_amount, 3),
            "total_minutes": round(total_minutes, 2) if total_minutes else None,
            "period_start": oldest.strftime("%d/%m/%Y") if oldest else None,
            "period_end": newest.strftime("%d/%m/%Y") if newest else None,
        }

    return {
        "shape": "generic",
        "row_count": len(evidence),
    }


def format_summary_for_prompt(summary):
    if summary["shape"] == "cross_source":
        lines = [
            "Nombre d'evenements: " + str(summary["event_count"]),
            "Montant total agrege: " + str(summary["total_charged"]) + " DT",
            "Periode: du " + str(summary["period_start"]) + " au " + str(summary["period_end"]),
            "Sources concernees: " + ", ".join(summary["sources"]),
        ]
        return "\n".join(lines)

    if summary["shape"] == "data_usage":
        lines = [
            "Nombre de sessions data: " + str(summary["session_count"]),
            "Volume total consomme: " + str(summary["total_volume_gb"]) + " GB",
            "Montant total facture: " + str(summary["total_charged"]) + " DT",
            "Periode: du " + str(summary["period_start"]) + " au " + str(summary["period_end"]),
        ]
        if summary.get("da_value"):
            lines.append("Bucket dedie: DA" + str(summary["da_value"]))
        return "\n".join(lines)

    if summary["shape"] == "sos_credit":
        lines = [
            "Nombre d'evenements de recouvrement: " + str(summary["event_count"]),
            "Nombre de prets concernes: " + str(summary["loan_count"]),
            "Montant total: " + str(summary["total_charged"]) + " DT",
            "Periode: du " + str(summary["period_start"]) + " au " + str(summary["period_end"]),
        ]
        return "\n".join(lines)

    if summary["shape"] == "sms_vas":
        lines = [
            "Nombre d'evenements factures: " + str(summary["event_count"]),
            "Montant total facture: " + str(summary["total_charged"]) + " DT",
            "Periode: du " + str(summary["period_start"]) + " au " + str(summary["period_end"]),
        ]
        if summary.get("services"):
            lines.append("Services concernes: " + ", ".join(summary["services"]))
        return "\n".join(lines)

    if summary["shape"] == "da_transactions":
        lines = [
            "Nombre de transactions: " + str(summary["transaction_count"]),
            "Montant total facture: " + str(summary["total_charged"]) + " DT",
            "Periode: du " + str(summary["period_start"]) + " au " + str(summary["period_end"]),
        ]
        if summary["balance_before"] is not None and summary["balance_after"] is not None:
            lines.append("Solde du compte dedie: " + str(summary["balance_before"]) + " DT au debut, " + str(summary["balance_after"]) + " DT a la fin")
        return "\n".join(lines)

    if summary["shape"] == "daily_usage":
        lines = [
            "Nombre de jours d'activite: " + str(summary["day_count"]),
            "Montant total facture: " + str(summary["total_amount"]) + " DT",
            "Periode: du " + str(summary["period_start"]) + " au " + str(summary["period_end"]),
        ]
        if summary.get("total_minutes"):
            lines.append("Duree totale: " + str(summary["total_minutes"]) + " minutes")
        return "\n".join(lines)

    return str(summary["row_count"]) + " enregistrement(s) trouve(s)."


def extract_numbers_from_text(text):
    text = text.replace("\u00a0", " ")
    matches = re.findall(r"\d+[.,]?\d*", text)
    numbers = []
    for m in matches:
        try:
            numbers.append(float(m.replace(",", ".")))
        except ValueError:
            continue
    return numbers


def key_figure_for(summary):
    if summary["shape"] == "cross_source":
        return summary["total_charged"]
    if summary["shape"] == "data_usage":
        return summary["total_volume_gb"]
    if summary["shape"] == "sos_credit":
        return summary["total_charged"]
    if summary["shape"] == "sms_vas":
        return summary["total_charged"]
    if summary["shape"] == "da_transactions":
        return summary["total_charged"]
    if summary["shape"] == "daily_usage":
        return summary["total_amount"]
    return None


def contains_correct_figure(explanation_text, expected_value, tolerance=0.02):
    if expected_value is None:
        return True
    found = extract_numbers_from_text(explanation_text)
    return any(abs(n - expected_value) <= tolerance for n in found)


FORBIDDEN_INTROS = [
    "voici l'explication",
    "voici une explication",
    "voici les details",
    "voici le detail",
]


def strip_forbidden_intro(text):
    """Removes a leading intro phrase if the model wrote one anyway,
    despite the rule against it. Deterministic cleanup, not a rewrite
    of any factual content."""
    stripped = text.strip()
    lowered = stripped.lower()

    for intro in FORBIDDEN_INTROS:
        if lowered.startswith(intro):
            stripped = stripped[len(intro):].lstrip(" :\n-")
            break

    stripped = stripped.strip('"').strip()
    return stripped


def build_prompt(category, formatted_summary, retry=False):
    retry_warning = ""
    if retry:
        retry_warning = "\nATTENTION: ta reponse precedente contenait un chiffre incorrect. Tu DOIS utiliser UNIQUEMENT les chiffres du resume ci-dessus, ne recopie pas l'exemple de style.\n"

    return (
        "Tu es un assistant qui redige des explications factuelles courtes pour un employe de Tunisie Telecom.\n"
        "Categorie de la reclamation: " + category + "\n\n"
        "Voici les SEULES donnees que tu dois utiliser pour ecrire l'explication:\n"
        + formatted_summary + "\n"
        + retry_warning + "\n"
        "Regles strictes (a respecter TOUTES sans exception):\n"
        "1. Sortie: 2 a 3 phrases maximum, prose continue, aucune liste, aucun guillemet autour de la reponse.\n"
        "2. N'ecris JAMAIS de phrase d'introduction (interdit: \"Voici l'explication\", \"Voici les details\", \"Voici une explication\", ou toute variante). Commence directement par le fait, sans aucun preambule.\n"
        "3. Utilise UNIQUEMENT les chiffres donnes ci-dessus. N'utilise JAMAIS de chiffres provenant d'un autre exemple ou d'une autre source.\n"
        "4. Ne mentionne jamais le nom brut de la categorie (" + category + ").\n"
        "5. Ne liste pas les transactions une par une.\n"
        "6. Ne recopie JAMAIS mot pour mot un exemple de style -- utilise uniquement sa structure grammaticale, jamais ses chiffres ni ses dates.\n\n"
        "Structure attendue (a titre d'exemple de STYLE uniquement, ne recopie aucun chiffre de cet exemple, et n'ecris pas de guillemets ni d'introduction):\n"
        "Le solde dedie a ete debite de [MONTANT] DT sur [NOMBRE] transactions entre le [DATE1] et le [DATE2].\n\n"
        "Explication (commence directement par le fait, sans introduction, sans guillemets):\n"
    )


def build_fallback_sentence(summary):
    if summary["shape"] == "cross_source":
        sentence = "Un montant agrege de " + str(summary["total_charged"]) + " DT a ete releve sur " + str(summary["event_count"]) + " evenement(s) repartis entre le " + str(summary["period_start"]) + " et le " + str(summary["period_end"]) + ", touchant plusieurs sources (" + ", ".join(summary["sources"]) + ")."
        return sentence

    if summary["shape"] == "data_usage":
        bucket = " DA" + str(summary["da_value"]) if summary.get("da_value") else ""
        sentence = "Le volume data du bucket dedie" + bucket + " a ete de " + str(summary["total_volume_gb"]) + " GB sur " + str(summary["session_count"]) + " session(s) entre le " + str(summary["period_start"]) + " et le " + str(summary["period_end"]) + "."
        sentence += " Montant total facture sur cette periode: " + str(summary["total_charged"]) + " DT."
        return sentence

    if summary["shape"] == "sos_credit":
        sentence = "Un credit SOS de " + str(summary["total_charged"]) + " DT a ete recouvre sur " + str(summary["event_count"]) + " evenement(s) concernant " + str(summary["loan_count"]) + " pret(s) entre le " + str(summary["period_start"]) + " et le " + str(summary["period_end"]) + "."
        return sentence

    if summary["shape"] == "sms_vas":
        sentence = "Le solde a ete debite de " + str(summary["total_charged"]) + " DT sur " + str(summary["event_count"]) + " evenement(s) entre le " + str(summary["period_start"]) + " et le " + str(summary["period_end"]) + "."
        if summary.get("services"):
            sentence += " Services concernes: " + ", ".join(summary["services"]) + "."
        return sentence

    if summary["shape"] == "da_transactions":
        sentence = "Le solde dedie DA" + str(summary["da_value"]) + " du client a ete debite de " + str(summary["total_charged"]) + " DT sur " + str(summary["transaction_count"]) + " transaction(s) entre le " + str(summary["period_start"]) + " et le " + str(summary["period_end"]) + "."
        if summary["balance_before"] is not None and summary["balance_after"] is not None:
            sentence += " Le solde de ce compte dedie est passe de " + str(summary["balance_before"]) + " DT a " + str(summary["balance_after"]) + " DT sur cette periode."
        return sentence

    if summary["shape"] == "daily_usage":
        sentence = "Le client a ete facture " + str(summary["total_amount"]) + " DT au total sur " + str(summary["day_count"]) + " jour(s) d'activite entre le " + str(summary["period_start"]) + " et le " + str(summary["period_end"]) + "."
        if summary.get("total_minutes"):
            sentence += " Duree totale enregistree: " + str(summary["total_minutes"]) + " minutes."
        return sentence

    if summary["shape"] == "renewal_failure":
        sentence = str(summary["attempt_count"]) + " tentative(s) de renouvellement automatique du forfait ont echoue (" + ", ".join(summary["reasons"]) + ") entre le " + str(summary["period_start"]) + " et le " + str(summary["period_end"]) + ". Le forfait a probablement expire faute de renouvellement reussi, sans debit ponctuel constate."
        return sentence

    if summary["shape"] == "da_adjustment":
        sentence = str(summary["adjustment_count"]) + " ajustement(s) de compte dedie ont ete trouves entre le " + str(summary["period_start"]) + " et le " + str(summary["period_end"]) + ", representant un mouvement de solde de " + str(summary["total_da_amount"]) + " (sens credit/debit non determine)."
        return sentence

    return str(summary["row_count"]) + " enregistrement(s) trouve(s) pour cette periode."


CONFIDENCE_CAVEATS = {
    "LOW": " Confiance faible : ceci est une piste possible, pas une cause confirmee -- il pourrait s'agir d'une coincidence de montant. Verification manuelle recommandee.",
    "MEDIUM": " Confiance moyenne : a confirmer si necessaire.",
}


def explain_investigation(category, evidence, confidence=None):
    """
    confidence (HIGH/MEDIUM/LOW, from find_best_match via the calling
    investigation service) drives a caveat appended deterministically
    after whatever explanation text is produced -- LLM-generated or the
    fallback sentence. This can't be left to the LLM prompt alone: a
    free-text model doesn't reliably keep a "not confirmed" warning in
    a short 2-3 sentence output, and the whole point of scoring
    confidence is that a LOW-confidence lead (e.g. a broad cross-source
    total that just happens to fall within tolerance) must never read
    the same as a HIGH-confidence one (a single matching transaction).
    """
    if not evidence:
        return "Aucun enregistrement correspondant n'a ete trouve pour cette reclamation. Une verification manuelle complementaire peut etre necessaire."

    summary = summarize_evidence(category, evidence)

    # These two shapes don't fit the "X DT debited" template every other
    # shape shares (a failed renewal debited nothing; an adjustment's
    # credit/debit direction isn't known) -- letting the free-text LLM
    # loose on them risks it defaulting to that template's language
    # anyway and inventing a debit that didn't happen. Skip straight to
    # the deterministic sentence instead of trusting a figure-check retry
    # to catch that after the fact.
    if summary["shape"] in ("renewal_failure", "da_adjustment"):
        return build_fallback_sentence(summary) + CONFIDENCE_CAVEATS.get(confidence, "")

    formatted = format_summary_for_prompt(summary)
    expected_figure = key_figure_for(summary)

    prompt = build_prompt(category, formatted, retry=False)
    explanation = ask_ollama(prompt, temperature=0.2)
    explanation = strip_forbidden_intro(explanation)

    if not contains_correct_figure(explanation, expected_figure):
        prompt_retry = build_prompt(category, formatted, retry=True)
        explanation_retry = ask_ollama(prompt_retry, temperature=0.1)
        explanation_retry = strip_forbidden_intro(explanation_retry)

        explanation = explanation_retry if contains_correct_figure(explanation_retry, expected_figure) \
            else build_fallback_sentence(summary)

    return explanation + CONFIDENCE_CAVEATS.get(confidence, "")
