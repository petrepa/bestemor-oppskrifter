# Bestemors oppskrifter

Eit søkbart arkiv av bestemors handskrivne oppskrifter, tekne vare på digitalt for framtidige generasjonar.

## Oversikt

Sjølve skanna oppskrifta er det du ser og les på nettstaden — det er «fasiten». Målet er å gjere skannane lette å finne att: søk etter t.d. «lefse», så kjem alle lefse-skannane opp, og du trykkjer deg inn til ei fin visning av originalen.

- **Nettstad** (`recipes-site/`) — Ein statisk nettstad bygd med [Astro](https://astro.build), hosta på GitHub Pages, med [Pagefind](https://pagefind.app)-søk
- **Automatisk indeksering** — Ein GitHub Action som brukar Claude API til å lese ut tittel, kategori, taggar og ei grov transkribering frå kvar skann, slik at arkivet blir søkbart

## Leggje til ei oppskrift frå skann

1. Last opp eit bilete av den handskrivne oppskrifta til `recipes-site/public/skannar/` (via GitHub-nettsida eller git push til `main`)
2. Ein GitHub Action køyrer automatisk og brukar Claude API til å:
   - Lese ut tittel, kategori og søkjetaggar
   - Lage ei grov transkribering som berre blir brukt til søk (treng ikkje vere korrekt — det er skannen som gjeld)
   - Gje biletefila eit nytt namn basert på tittelen og lage ei `.md`-fil
3. Endringa blir **committa rett til `main`** og nettstaden byggjast på nytt — ingen manuell godkjenning trengst

Vil du køyre ei skann på nytt, bruk **Actions → Ingest recipe scan → Run workflow** og oppgje filnamnet/-a.

### Oppsett av automatisk konvertering

For at GitHub Action-en skal fungere, må du leggje til ein API-nøkkel:

1. Gå til **Settings → Secrets and variables → Actions** i GitHub-repoet
2. Legg til ein ny secret: `ANTHROPIC_API_KEY` med din Claude API-nøkkel

## Leggje til ei oppskrift manuelt

Sjå [GUIDE.md](GUIDE.md) for ei detaljert steg-for-steg-rettleiing, eller bruk [TEMPLATE.md](TEMPLATE.md) som utgangspunkt.

**Kort oppsummert:**

1. Legg originalskannen i `recipes-site/public/skannar/`
2. Lag ei ny `.md`-fil i `recipes-site/src/content/oppskrifter/`
3. Legg til frontmatter med tittel, tags, kategori, dato og `original_skann`
4. Skriv ei grov transkribering i brødteksten (til søk)
5. Push til `main`-branchen — nettstaden byggjast og deployast automatisk

## Oppsett og utvikling

### Nettstad

```bash
cd recipes-site
npm install
npm run dev      # Start utviklingsserver
npm run build    # Bygg for produksjon (inkl. Pagefind søkeindeks)
```

### Deploy

Nettstaden deployast automatisk til GitHub Pages via GitHub Actions når du pushar til `main`.

For at dette skal fungere:

1. Gå til **Settings → Pages** i GitHub-repoet
2. Set **Source** til **GitHub Actions**

## Teknisk stack

- [Astro](https://astro.build) — Statisk nettstad-generator
- [Pagefind](https://pagefind.app) — Klient-side søk
- [Claude API](https://docs.anthropic.com) — Automatisk transkripsjon via GitHub Actions
