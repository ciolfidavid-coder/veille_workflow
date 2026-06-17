import re
from datetime import datetime

from playwright.sync_api import sync_playwright

SOURCE = "ECB (Supervision bancaire)"
URL = (
    "https://www.bankingsupervision.europa.eu/press/pubbydate/html/"
    "index.en.html?name_of_publication=Press%20release"
)
BASE_URL = "https://www.bankingsupervision.europa.eu"


def demander_date(message):
    while True:
        try:
            return datetime.strptime(input(message), "%d/%m/%Y")
        except ValueError:
            print("❌ Format invalide. Utilise JJ/MM/AAAA.")


def nettoyer_texte(text):
    return re.sub(r"\s+", " ", text).strip()


def resumer_texte(text, n=3):
    sentences = [s.strip() for s in re.split(r"[.!?]", text) if len(s.strip()) > 40]
    return ". ".join(sentences[:n]) + "." if sentences else "Résumé indisponible."


def accept_cookies(page):
    for label in ("I understand and I accept the use of cookies", "Accept", "I understand"):
        button = page.locator(f"button:has-text('{label}')")
        if button.count():
            button.first.click()
            page.wait_for_timeout(500)
            return


def collecter_communiques(page):
    releases = []

    for dt, dd in zip(page.locator("dt").all(), page.locator("dd").all()):
        date_text = nettoyer_texte(dt.inner_text())
        try:
            pub_date = datetime.strptime(date_text, "%d %B %Y")
        except ValueError:
            continue

        link = dd.locator(
            "a[href*='/press/pr/date/'][href$='.en.html']:not([href*='_annex_'])"
        ).first
        if not link.count():
            continue

        href = link.get_attribute("href")
        title = nettoyer_texte(link.inner_text())
        if not href or not title:
            continue

        releases.append(
            {
                "pub_date": pub_date,
                "title": title,
                "link": href if href.startswith("http") else BASE_URL + href,
            }
        )

    return releases


def extraire_contenu_page(page, url):
    page.goto(url, wait_until="networkidle")
    page.wait_for_selector(".section-press", timeout=15000)

    paragraphs = [
        nettoyer_texte(p.inner_text())
        for p in page.locator(".section-press p").all()
        if len(nettoyer_texte(p.inner_text())) > 40
    ]
    return nettoyer_texte(" ".join(paragraphs))


def run(date_debut, date_fin, verbose=True):
    resultats = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(URL, wait_until="networkidle")
        accept_cookies(page)

        for _ in range(10):
            page.mouse.wheel(0, 2000)
            page.wait_for_timeout(300)

        releases = collecter_communiques(page)

        for item in releases:
            if not (date_debut.date() <= item["pub_date"].date() <= date_fin.date()):
                continue

            contenu = extraire_contenu_page(page, item["link"])
            resume = resumer_texte(contenu or item["title"])
            resultats.append((item["pub_date"], item["title"], item["link"], resume))

        browser.close()

    if not resultats:
        if verbose:
            print("Aucun communiqué trouvé pour cette période.")
        return resultats

    resumes_globaux = []
    for pub_date, title, link, resume in sorted(resultats, reverse=True):
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
