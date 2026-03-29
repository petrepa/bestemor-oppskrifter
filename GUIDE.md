# Korleis leggje til ei ny oppskrift

Denne guiden forklarer korleis du legg til ei ny oppskrift på nettstaden.

## Steg for steg

### 1. Lag ei ny Markdown-fil

Lag ei ny `.md`-fil i mappa `recipes-site/src/content/oppskrifter/`. Filnamnet bør vere ein slug av tittelen, t.d. `bestemors-vaflar.md`.

### 2. Legg til frontmatter

Kvar oppskriftfil startar med ein YAML-blokk mellom `---`. Her er eit eksempel:

```yaml
---
tittel: "Bestemors vaflar"
tags: ["bakverk", "frukost", "tradisjonelt"]
kategori: "Bakverk"
dato: 2024-01-15
original_skann: "skannar/vaflar-original.jpg"
---
```

**Forklaring:**

| Felt             | Skildring                                               | Påkravd? |
| ---------------- | ------------------------------------------------------- | -------- |
| `tittel`         | Namn på oppskrifta                                      | Ja       |
| `tags`           | Liste med taggar (i klammer, med hermeteikn)             | Ja       |
| `kategori`       | Hovudkategori                                            | Ja       |
| `dato`           | Dato i format YYYY-MM-DD                                 | Ja       |
| `original_skann` | Sti til originalbilete (utan leiande `/`)                | Nei      |

### 3. Tilgjengelege kategoriar

- Bakverk
- Middag
- Supper og gryter
- Fisk og sjømat
- Dessert
- Frukost
- Drikke og saft
- Sylting og konservering
- Tradisjonelt og høgtid

Du kan leggje til nye kategoriar ved behov.

### 4. Skriv oppskrifta

Etter frontmatter-blokka skriv du sjølve oppskrifta i vanleg Markdown:

```markdown
## Ingrediensar

- 3 egg
- 150 g sukker

## Framgangsmåte

1. Pisk egg og sukker luftig.
2. Tilsett smør.
```

### 5. Legg til originalskann (valfritt)

Om du har eit bilete av den originale handskrivne oppskrifta:

1. Legg biletet i `recipes-site/public/skannar/`
2. Set `original_skann`-feltet i frontmatter til `skannar/filnamn.jpg`

### 6. Push til GitHub

Når du pushar endringa til `main`-branchen, vil nettstaden automatisk byggjast og deployast.
