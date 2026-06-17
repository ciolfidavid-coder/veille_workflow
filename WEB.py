import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS

OLLAMA_URL = "http://localhost:11434/api/generate"
MODELES_PRIORITAIRES = ("qwen2.5:7b", "mistral:7b")
NB_RESULTATS = 4
MAX_CHARS_SOURCE = 1400
TIMEOUT_PAGE = 8
SEUIL_EXTRAIT_SUFFISANT = 350
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}
DOMAINES_IGNORES = (
    "larousse.fr", "cnrtl.fr", "lerobert.com", "lalanguefrancaise.com",
    "wiktionary.org", "wordreference.com", "linguee.", "babla.", "reverso.",
    "facebook.com", "instagram.com", "twitter.com", "x.com", "tiktok.com",
)
URLS_PREVISIONS = ("price-prediction", "prevision", "prévision", "prediction")
DOMAINES_PRIORITAIRES = (
    "defense.gouv.fr", "lemonde.fr/live", "liveuamap", "ouest-france.fr",
    "lefigaro.fr", "france24.com", "rfi.fr", "bbc.com", "reuters.com",
)
MOIS_FR = {
    "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "aout": 8, "août": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12, "décembre": 12,
}
MOIS_FR_NOM = {
    1: "janvier", 2: "février", 3: "mars", 4: "avril", 5: "mai", 6: "juin",
    7: "juillet", 8: "août", 9: "septembre", 10: "octobre", 11: "novembre", 12: "décembre",
}

MODELE = MODELES_PRIORITAIRES[0]


def _detecter_modele():
    global MODELE
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=5)
        resp.raise_for_status()
        installes = {m["name"] for m in resp.json().get("models", [])}
        for nom in MODELES_PRIORITAIRES:
            if nom in installes or any(n.startswith(nom.split(":")[0]) for n in installes):
                MODELE = nom
                return
    except requests.RequestException:
        pass


def nettoyer_texte(texte):
    return re.sub(r"\s+", " ", texte).strip()


def _normaliser(texte):
    return texte.lower().replace("'", " ").replace("'", " ")


def _extraire_date_question(question):
    q = _normaliser(question)
    if re.search(r"\baujourd\s*hui\b", q):
        return date.today()

    match = re.search(r"(?:au|le|du)\s+(\d{1,2})[/-](\d{1,2})[/-](\d{4})", q)
    if match:
        j, m, a = map(int, match.groups())
        try:
            return date(a, m, j)
        except ValueError:
            pass

    match = re.search(r"(?:au|le|du)\s+(\d{1,2})\s+([a-zéèêëàâùûôîïü]+)\s+(\d{4})", q)
    if match:
        j, mois_nom, a = int(match.group(1)), match.group(2), int(match.group(3))
        mois = MOIS_FR.get(mois_nom)
        if mois:
            try:
                return date(a, mois, j)
            except ValueError:
                pass
    return None


def est_question_actualite(question):
    q = _normaliser(question)
    if re.search(
        r"où en est|ou en est|point sur|situation|état des lieux|aujourd|actuel|"
        r"dernières nouvelles|en direct|ce jour|hier|cette semaine|actualit",
        q,
    ):
        return True
    if re.search(r"\b(cours|prix|taux)\b", q):
        return True
    return _extraire_date_question(question) is not None


def reformuler_recherche(question):
    q = nettoyer_texte(question)
    q = re.sub(
        r"^(qui est|qui etait|qui était|qu est ce que|qu'est-ce que|c est quoi|c'est quoi|"
        r"quelle est|quel est|quelles sont|quels sont|combien|où en est|ou en est|"
        r"où se trouve|ou se trouve|comment|pourquoi|peux tu|peux-tu)\s+",
        "",
        q,
        flags=re.IGNORECASE,
    )
    q = q.strip(" ?.!")

    date_q = _extraire_date_question(question)
    if date_q:
        libelle = f"{date_q.day} {MOIS_FR_NOM[date_q.month]} {date_q.year}"
        if libelle.lower() not in q.lower():
            q = f"{q} {libelle}"

    if est_question_actualite(question):
        q += " actualité"
    return q


def compresser_contenu(question, texte, max_chars=MAX_CHARS_SOURCE):
    """Garde les phrases pertinentes → moins de tokens, réponse plus rapide et précise."""
    mots_cles = {
        m for m in re.findall(r"[a-zéèêëàâùûôîïü]{4,}", _normaliser(question))
        if m not in {"quel", "quelle", "quels", "quelles", "comment", "pourquoi", "estce"}
    }
    annee = str(date.today().year)
    phrases = re.split(r"(?<=[.!?])\s+", texte)
    notees = []
    for phrase in phrases:
        p = phrase.strip()
        if len(p) < 30:
            continue
        p_norm = p.lower()
        score = sum(1 for m in mots_cles if m in p_norm)
        if annee in p or re.search(r"\b202[4-6]\b", p):
            score += 3
        if re.search(r"\b\d+\b", p):
            score += 1
        if score > 0:
            notees.append((score, p))

    notees.sort(key=lambda x: x[0], reverse=True)
    selection, total = [], 0
    for _, phrase in notees:
        if total + len(phrase) > max_chars:
            break
        selection.append(phrase)
        total += len(phrase)

    return " ".join(selection) if selection else texte[:max_chars]


def _url_valide(url, exclure_previsions=False):
    if not url or not url.startswith("http"):
        return False
    url_lower = url.lower()
    if any(d in url_lower for d in DOMAINES_IGNORES):
        return False
    if exclure_previsions and any(p in url_lower for p in URLS_PREVISIONS):
        return False
    return True


def _score_resultat(item):
    url = item["url"].lower()
    score = 0
    if item.get("source_moteur") == "actualités":
        score += 20
    if any(d in url for d in DOMAINES_PRIORITAIRES):
        score += 15
    if any(m in url for m in ("live", "en-direct", "point-situation")):
        score += 10
    if "wikipedia.org" in url:
        score += 5 if ("chronologie" in url or "2026" in url) else -10
    titre = (item.get("titre") or "").lower()
    extrait = (item.get("extrait") or "").lower()
    if "2026" in extrait or "2026" in titre:
        score += 8
    if re.search(r"\b202[0-3]\b", extrait) and "2026" not in extrait:
        score -= 8
    return score


def _rechercher_ddg_text(requete, nb, exclure_previsions=False):
    resultats, vus = [], set()
    try:
        with DDGS() as ddgs:
            for item in ddgs.text(requete, max_results=nb + 6, region="fr-fr"):
                href = item.get("href")
                if href and _url_valide(href, exclure_previsions) and href not in vus:
                    vus.add(href)
                    resultats.append({
                        "url": href, "titre": item.get("title", ""),
                        "extrait": item.get("body", ""), "source_moteur": "web",
                    })
    except Exception:
        pass
    return resultats


def _rechercher_ddg_news(requete, nb):
    resultats, vus = [], set()
    try:
        with DDGS() as ddgs:
            for item in ddgs.news(requete, max_results=nb + 6, region="fr-fr"):
                href = item.get("url") or item.get("href")
                if href and _url_valide(href) and href not in vus:
                    vus.add(href)
                    resultats.append({
                        "url": href, "titre": item.get("title", ""),
                        "extrait": item.get("body", ""), "source_moteur": "actualités",
                        "date": item.get("date", ""),
                    })
    except Exception:
        pass
    return resultats


def _requetes_complementaires(question, requete):
    requetes = [requete]
    q, base = _normaliser(question), requete.replace(" actualité", "").strip()
    if re.search(r"où en est|ou en est|point sur|situation", q):
        requetes.append(f"{base} point situation")
    if re.search(r"guerre|conflit|front|militaire|armée", q):
        requetes.append(f"{base} ministère armées")
    return requetes[:2]


def rechercher_web(question, requete):
    actu, vus, resultats = est_question_actualite(question), set(), []
    for req in _requetes_complementaires(question, requete):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_rechercher_ddg_text, req, NB_RESULTATS, actu)]
            if actu:
                futures.insert(0, pool.submit(_rechercher_ddg_news, req, NB_RESULTATS))
            for fut in as_completed(futures):
                for item in fut.result():
                    if item["url"] not in vus:
                        vus.add(item["url"])
                        resultats.append(item)
    resultats.sort(key=_score_resultat, reverse=True)
    return resultats[:NB_RESULTATS]


def extraire_contenu_page(url, max_caracteres=2500):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT_PAGE)
        resp.raise_for_status()
    except requests.RequestException:
        return None
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    texte = nettoyer_texte(soup.get_text(separator=" "))
    return texte[:max_caracteres] if len(texte) >= 80 else None


def _construire_contenu_source(item, contenu_page, question):
    parties = []
    if item.get("date"):
        parties.append(f"Date : {item['date']}")
    if item.get("titre"):
        parties.append(f"Titre : {item['titre']}")
    if item.get("extrait"):
        parties.append(item["extrait"])
    if contenu_page:
        parties.append(contenu_page)
    return compresser_contenu(question, " ".join(parties))


def _doit_lire_page(item):
    return not (
        item.get("source_moteur") == "actualités"
        and len(item.get("extrait", "")) >= SEUIL_EXTRAIT_SUFFISANT
    )


def collecter_sources(question):
    requete = reformuler_recherche(question)
    print(f"\n🔎 Recherche : « {requete} »")
    if est_question_actualite(question):
        print("   (priorité actualité)")

    resultats = rechercher_web(question, requete)
    if not resultats:
        print("❌ Aucun résultat trouvé.")
        return []

    a_lire = [(i, item) for i, item in enumerate(resultats) if _doit_lire_page(item)]
    contenus = {}
    if a_lire:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futurs = {pool.submit(extraire_contenu_page, item["url"]): i for i, item in a_lire}
            for fut in as_completed(futurs):
                contenus[futurs[fut]] = fut.result()

    sources = []
    for i, item in enumerate(resultats):
        print(f"  • {item['url']}")
        texte = _construire_contenu_source(item, contenus.get(i), question)
        if len(texte) >= 60:
            sources.append({"url": item["url"], "contenu": texte})
    return sources


def construire_prompt(question, sources):
    blocs = [f"[{i}] {s['url']}\n{s['contenu']}" for i, s in enumerate(sources, 1)]
    aujourdhui = date.today().strftime("%d/%m/%Y")
    date_cible = _extraire_date_question(question)
    periode = (
        f"Date ciblée : {date_cible.strftime('%d/%m/%Y')}. "
        "Réponds sur CETTE période uniquement."
        if date_cible else "Privilégie les faits les plus récents."
    )

    return (
        f"/no_think\n"
        f"Date du jour : {aujourdhui}. {periode}\n"
        "Tu synthétises des sources web en français, style rapport structuré.\n\n"
        "FORMAT OBLIGATOIRE :\n"
        "## Réponse directe\n"
        "(2-3 phrases qui répondent à la question)\n\n"
        "## Points clés\n"
        "(- puces avec chiffres, lieux, noms, dates précises)\n\n"
        "## Synthèse\n"
        "(1-2 phrases de conclusion)\n\n"
        "## Sources\n"
        "(liste des URLs)\n\n"
        "RÈGLES : français uniquement ; pas de contexte historique général ; "
        "ignore les infos de 2022-2024 sauf si indispensables ; "
        "uniquement les faits des extraits ci-dessous.\n\n"
        f"QUESTION : {question}\n\n"
        f"EXTRAITS :\n" + "\n---\n".join(blocs) + "\n\n"
        "RÉPONSE :"
    )


def analyser_avec_ollama(question, sources):
    prompt = construire_prompt(question, sources)
    print(f"\n🤖 Synthèse par {MODELE}...\n")
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": MODELE,
                "prompt": prompt,
                "stream": True,
                "options": {
                    "temperature": 0.15,
                    "num_predict": 750,
                    "num_ctx": 8192,
                },
            },
            stream=True,
            timeout=180,
        )
        resp.raise_for_status()
    except requests.RequestException:
        print("❌ Ollama indisponible. Lancez : ollama serve")
        return None

    morceaux = []
    for ligne in resp.iter_lines():
        if not ligne:
            continue
        data = json.loads(ligne)
        fragment = data.get("response", "")
        if fragment:
            print(fragment, end="", flush=True)
            morceaux.append(fragment)
        if data.get("done"):
            break
    print()
    return "".join(morceaux).strip()


def poser_question():
    question = input("❓ Posez votre question : ").strip()
    while not question:
        question = input("❓ Posez votre question : ").strip()
    return question


def run():
    question = poser_question()
    sources = collecter_sources(question)
    if not sources:
        return

    print("=" * 80)
    reponse = analyser_avec_ollama(question, sources)
    if not reponse:
        return
    print("=" * 80)


if __name__ == "__main__":
    _detecter_modele()
    print("🌐 Assistant web (recherche + Ollama)")
    print(f"   Modèle : {MODELE}")
    print("   Astuce : installez qwen2.5:7b pour le meilleur compromis vitesse/qualité\n")
    run()
