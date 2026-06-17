import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

SOURCE = "EBA"
BASE_URL = "https://www.eba.europa.eu"
URL = BASE_URL + "/publications-and-media/press-releases"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def demander_date(message):
    while True:
        date_str = input(message)
        try:
            return datetime.strptime(date_str, "%d/%m/%Y")
        except ValueError:
            print("❌ Format invalide. Utilise JJ/MM/AAAA.")


def nettoyer_texte(html):
    text = re.sub(r"\s+", " ", html)
    return text.strip()


def extraire_contenu_page(url):
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    selecteurs = [
        ("div", {"class": "field--name-body"}),
        ("div", {"class": "field--name-field-body"}),
        ("div", {"class": "text-long"}),
        ("article", {}),
    ]

    for tag, attrs in selecteurs:
        bloc = soup.find(tag, attrs)
        if bloc:
            texte = bloc.get_text(separator=" ", strip=True)
            if len(texte) > 150:
                return nettoyer_texte(texte)

    paragraphs = soup.find_all("p")
    texte = " ".join(p.get_text(strip=True) for p in paragraphs)
    return nettoyer_texte(texte) if len(texte) > 150 else ""


def resumer_texte(texte, nb_phrases=3):
    phrases = re.split(r"[.!?]", texte)
    phrases = [p.strip() for p in phrases if len(p.strip()) > 40]
    return ". ".join(phrases[:nb_phrases]) + "." if phrases else "Résumé indisponible."


def collecter_communiques(date_debut, date_fin):
    response = requests.get(URL, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    resultats = []

    for item in soup.find_all("div", class_="views-row"):
        date_tag = item.find("div", class_="link-icon--calendar")
        if not date_tag:
            continue

        try:
            pub_date = datetime.strptime(date_tag.get_text(strip=True).title(), "%d %B %Y")
        except ValueError:
            continue

        if not (date_debut.date() <= pub_date.date() <= date_fin.date()):
            continue

        link_tag = item.find("a")
        if not link_tag or not link_tag.get("href"):
            continue

        resultats.append(
            (
                pub_date,
                link_tag.get_text(strip=True),
                BASE_URL + link_tag["href"],
            )
        )

    return resultats


def run(date_debut, date_fin, verbose=True):
    communiques = collecter_communiques(date_debut, date_fin)
    resultats = []

    if not communiques:
        if verbose:
            print("Aucun communiqué trouvé pour cette période.")
        return resultats

    resumes_globaux = []
    for pub_date, title, link in sorted(communiques, reverse=True):
        contenu = extraire_contenu_page(link)
        resume = resumer_texte(contenu)
        resultats.append((pub_date, title, link, resume))

        if verbose:
            print(f"\n📅 {pub_date.strftime('%d/%m/%Y')} — {title}")
            print(link)
            print("📝 Résumé :")
            print(resume)
            resumes_globaux.append(resume)

    if verbose and resumes_globaux:
        print("\n" + "=" * 80)
        print("📊 RÉSUMÉ GLOBAL DE LA PÉRIODE")
        print("=" * 80)
        print("\n".join(resumes_globaux))

    return resultats


if __name__ == "__main__":
    print("👉 Entrez les dates au format JJ/MM/AAAA")
    date_debut = demander_date("Date de début : ")
    date_fin = demander_date("Date de fin   : ")

    if date_fin < date_debut:
        date_debut, date_fin = date_fin, date_debut

    run(date_debut, date_fin)
