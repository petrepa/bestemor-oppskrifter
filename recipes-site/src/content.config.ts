import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

const oppskrifter = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/oppskrifter' }),
  schema: z.object({
    tittel: z.string(),
    tags: z.array(z.string()),
    kategori: z.string(),
    dato: z.date(),
    original_skann: z.string(),
    // Which physical book the scan comes from — id of an entry in the boker
    // collection (e.g. "groneboka"). Optional: older recipes may lack a source.
    kjelde: z.string().optional(),
  }),
});

// The physical recipe books the scans come from.
const boker = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/boker' }),
  schema: z.object({
    namn: z.string(),
    bilete: z.string(), // cover photo, path under public/ (e.g. "boker/groneboka.jpg")
  }),
});

export const collections = {
  oppskrifter,
  boker,
};
