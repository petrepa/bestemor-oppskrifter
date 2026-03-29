import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

const oppskrifter = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/oppskrifter' }),
  schema: z.object({
    tittel: z.string(),
    tags: z.array(z.string()),
    kategori: z.string(),
    dato: z.date(),
    original_skann: z.string().optional(),
  }),
});

export const collections = {
  oppskrifter,
};
