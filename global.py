from datetime import datetime

import EBAv2
import ECB3
import SRB

SOURCES = (
    (EBAv2.SOURCE, EBAv2.run),
    (ECB3.SOURCE, ECB3.run),
    (SRB.SOURCE, SRB.run),
)


def demander_date(message):
    while True:
        date_str = input(message)
        try:
            return datetime.strptime(date_str, "%d/%m/%Y")
        except ValueError:
            print("❌ Format invalide. Utilise JJ/MM/AAAA.")


def afficher_entete(source):
    print("\n" + "#" * 80)
    print(f"# {source}")
    print("#" * 80)


def main():
    print("👉 Entrez les dates au format JJ/MM/AAAA")
    date_debut = demander_date("Date de début : ")
    date_fin = demander_date("Date de fin   : ")

    if date_fin < date_debut:
        date_debut, date_fin = date_fin, date_debut

    print(
        f"\n🔎 Recherche des communiqués du "
        f"{date_debut.strftime('%d/%m/%Y')} au {date_fin.strftime('%d/%m/%Y')}"
    )

    totaux = {}
    for source, run_source in SOURCES:
        afficher_entete(source)
        resultats = run_source(date_debut, date_fin, verbose=True)
        totaux[source] = len(resultats)

    print("\n" + "=" * 80)
    print("📊 SYNTHÈSE GLOBALE")
    print("=" * 80)
    total_general = 0
    for source, count in totaux.items():
        print(f"  • {source} : {count} communiqué(s)")
        total_general += count
    print(f"\nTotal : {total_general} communiqué(s)")


if __name__ == "__main__":
    main()
