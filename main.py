import sys
import os
from datetime import datetime
from supabase import create_client

import EBAv2
import ECB3
import SRB

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

SOURCES = [
    (EBAv2.SOURCE, EBAv2.run),
    (ECB3.SOURCE, ECB3.run),
    (SRB.SOURCE, SRB.run),
]

def main():
    date_debut = datetime.strptime(sys.argv[1], "%d/%m/%Y")
    date_fin = datetime.strptime(sys.argv[2], "%d/%m/%Y")

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    for source, run_source in SOURCES:
        resultats = run_source(date_debut, date_fin, verbose=False)
        for pub_date, title, link, resume in resultats:
            supabase.table("veille_articles").upsert({
                "source": source,
                "pub_date": pub_date.strftime("%Y-%m-%d"),
                "title": title,
                "link": link,
                "resume": resume
            }, on_conflict="link").execute()

    print("Done")

if __name__ == "__main__":
    main()
