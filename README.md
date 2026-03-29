# Bestemors oppskrifter

Ei kjærleg samling av bestemors handskrivne oppskrifter, tekne vare på digitalt for framtidige generasjonar.

## Oversikt

- **Nettstad** (`recipes-site/`) — Ein statisk nettstad bygd med [Astro](https://astro.build), hostet på GitHub Pages
- **Automatisk konvertering** — Ein GitHub Action som brukar Claude API til å konvertere skannar av handskrivne oppskrifter til Markdown

## Leggje til ei oppskrift frå skann

Den enklaste måten å digitalisere ei oppskrift:

1. Last opp eit bilete av den handskrivne oppskrifta til `recipes-site/public/skannar/` (via GitHub-nettsida eller git push)
2. Ein GitHub Action køyrer automatisk og brukar Claude API til å:
   - Transkribere og konvertere oppskrifta til ei `.md`-fil
   - Gje biletefila eit nytt namn basert på oppskrifttittelen
3. Det vert oppretta ein **pull request** som du kan gå gjennom og godkjenne

### Oppsett av automatisk konvertering

For at GitHub Action-en skal fungere, må du leggje til ein API-nøkkel:

1. Gå til **Settings → Secrets and variables → Actions** i GitHub-repoet
2. Legg til ein ny secret: `ANTHROPIC_API_KEY` med din Claude API-nøkkel

## Leggje til ei oppskrift manuelt

Sjå [GUIDE.md](GUIDE.md) for ei detaljert steg-for-steg-rettleiing, eller bruk [TEMPLATE.md](TEMPLATE.md) som utgangspunkt.

**Kort oppsummert:**

1. Lag ei ny `.md`-fil i `recipes-site/src/content/oppskrifter/`
2. Legg til frontmatter med tittel, tags, kategori og dato
3. Skriv ingrediensar og framgangsmåte i Markdown
4. (Valfritt) Legg originalskann i `recipes-site/public/skannar/`
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
