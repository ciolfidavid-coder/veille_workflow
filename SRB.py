import re
from datetime import datetime
from urllib.parse import urljoin
import time
import requests
from bs4 import BeautifulSoup

SOURCE = "SRB"
BASE_URL = "https://srb.europa.eu"
URL = f"{BASE_URL}/en/news/search?f%5B0%5D=category%3Asrb_news_category%3A42"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}



def extraire_communiques():
    resultats = []
    vus = set()
    page = 0

    while True:
        resp = requests.get(f"{URL}&page={page}", headers=HEADERS, timeout=30)
        if resp.status_code == 429:
            time.sleep(5)
            continue
        resp.raise_for_status()
        batch = _parser_page(resp.text)
        if not batch:
            break

        for item in batch:
            if item[2] not in vus:
                vus.add(item[2])
                resultats.append(item)

        page += 1
        time.sleep(1)  # délai entre chaque page

    return resultats
    
def demander_date(message):
    while True:
        date_str = input(message)
        try:
            return datetime.strptime(date_str, "%d/%m/%Y")
        except ValueError:
            print("❌ Format invalide. Utilise JJ/MM/AAAA.")


def nettoyer_texte(t):
    return re.sub(r"\s+", " ", t).strip()


def resumer_texte(texte, nb_phrases=3):
    phrases = re.split(r"[.!?]", texte)
    phrases = [p.strip() for p in phrases if len(p.strip()) > 40]
    return ". ".join(phrases[:nb_phrases]) + "." if phrases else "Résumé indisponible."


def _parser_page(html):
    soup = BeautifulSoup(html, "html.parser")
    resultats = []

    for article in soup.select("article.node--view-mode-search-result"):
        link = article.select_one(".srb-news__title a[href]")
        time_el = article.select_one("time[datetime]")
        if not link or not time_el:
            continue

        pub_date = datetime.fromisoformat(time_el["datetime"])
        titre = nettoyer_texte(link.get_text())
        href = urljoin(BASE_URL, link["href"])
        resultats.append((pub_date, titre, href))

    return resultats


def extraire_communiques():
    resultats = []
    vus = set()
    page = 0

    while True:
        resp = requests.get(f"{URL}&page={page}", headers=HEADERS, timeout=30)
        resp.raise_for_status()
        batch = _parser_page(resp.text)
        if not batch:
            break

        for item in batch:
            if item[2] not in vus:
                vus.add(item[2])
                resultats.append(item)

        page += 1

    return resultats


def extraire_contenu_page(url):
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    main = soup.find("main")
    paragraphs = main.find_all("p") if main else soup.find_all("p")
    return " ".join(nettoyer_texte(p.get_text()) for p in paragraphs)


def run(date_debut, date_fin, verbose=True):
    communiques = extraire_communiques()
    filtrés = [
        (d, t, l) for (d, t, l) in communiques
        if date_debut.date() <= d.date() <= date_fin.date()
    ]

    if not filtrés:
        if verbose:
            print("Aucun communiqué trouvé pour cette période.")
        return []

    resultats = []
    resumes_globaux = []

    for pub_date, titre, lien in sorted(filtrés, reverse=True):
        contenu = extraire_contenu_page(lien)
        resume = resumer_texte(contenu)
        resultats.append((pub_date, titre, lien, resume))

        if verbose:
            print(f"\n📅 {pub_date.strftime('%d/%m/%Y')} — {titre}")
            print(lien)
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
